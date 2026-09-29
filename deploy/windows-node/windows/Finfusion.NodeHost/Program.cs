using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

internal static class Program
{
    private const string PipeName = "Finfusion.NodeControl.v1";
    private const string Distro = "FinfusionNode";
    private static readonly CancellationTokenSource Shutdown = new();
    private static ServiceMainDelegate? _serviceMain;
    private static HandlerDelegate? _handler;
    private static IntPtr _statusHandle;
    private static ServiceStatus _status;

    private static readonly HashSet<string> AllowedCommands = new(StringComparer.OrdinalIgnoreCase)
    {
        "status", "configure", "activate", "deactivate", "start", "stop", "restart",
        "backup", "restore", "doctor", "logs", "update"
    };

    public static async Task<int> Main(string[] args)
    {
        if (args.Length == 1 && args[0].Equals("service", StringComparison.OrdinalIgnoreCase))
            return RunAsService();
        if (args.Length == 0) return Usage();
        string command = args[0].ToLowerInvariant();
        if (!AllowedCommands.Contains(command)) return Usage();
        return await RunClient(command, args.Skip(1).ToArray());
    }

    private static int Usage()
    {
        Console.Error.WriteLine("Usage: FinfusionServer-NodeHost <command> [arguments]; restore requires VAULT.age IDENTITY.txt");
        return 64;
    }

    private static int RunAsService()
    {
        _serviceMain = ServiceMain;
        var table = new[] { new ServiceTableEntry { name = "FinfusionNodeHost", callback = _serviceMain }, new ServiceTableEntry() };
        if (!StartServiceCtrlDispatcher(table)) return Marshal.GetLastWin32Error();
        return 0;
    }

    private static void ServiceMain(int argc, IntPtr argv)
    {
        _handler = Handler;
        _statusHandle = RegisterServiceCtrlHandlerEx("FinfusionNodeHost", _handler, IntPtr.Zero);
        _status = new ServiceStatus { serviceType = 0x10, currentState = 2, controlsAccepted = 1, waitHint = 15000 };
        SetServiceStatus(_statusHandle, ref _status);
        try
        {
            // A host restart is always a fail-closed boundary.
            RunWslAsync("deactivate", Array.Empty<string>(), CancellationToken.None).GetAwaiter().GetResult();
            _status.currentState = 4;
            _status.waitHint = 0;
            SetServiceStatus(_statusHandle, ref _status);
            ServePipesAsync(Shutdown.Token).GetAwaiter().GetResult();
        }
        finally
        {
            try { RunWslAsync("deactivate", Array.Empty<string>(), CancellationToken.None).GetAwaiter().GetResult(); } catch { }
            _status.currentState = 1;
            _status.controlsAccepted = 0;
            SetServiceStatus(_statusHandle, ref _status);
        }
    }

    private static int Handler(int control, int eventType, IntPtr eventData, IntPtr context)
    {
        if (control is 1 or 5)
        {
            _status.currentState = 3;
            _status.waitHint = 10000;
            SetServiceStatus(_statusHandle, ref _status);
            Shutdown.Cancel();
        }
        return 0;
    }

    private static NamedPipeServerStream CreateSecuredPipe()
    {
        var security = new PipeSecurity();
        security.SetAccessRuleProtection(true, false);
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null), PipeAccessRights.ReadWrite, AccessControlType.Allow));
        return NamedPipeServerStreamAcl.Create(PipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.WriteThrough, 8192, 8192, security);
    }

    private static async Task ServePipesAsync(CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            await using var pipe = CreateSecuredPipe();
            try
            {
                await pipe.WaitForConnectionAsync(cancellation);
                using var reader = new StreamReader(pipe, new UTF8Encoding(false), false, 8192, leaveOpen: true);
                using var writer = new StreamWriter(pipe, new UTF8Encoding(false), 8192, leaveOpen: true) { AutoFlush = true };
                string? line = await reader.ReadLineAsync(cancellation);
                Response response = await HandleRequest(line, cancellation);
                await writer.WriteLineAsync(JsonSerializer.Serialize(response));
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { break; }
            catch (Exception ex) { EventLogWrite("Control request failed: " + ex.GetType().Name); }
        }
    }

    private static async Task<Response> HandleRequest(string? line, CancellationToken cancellation)
    {
        try
        {
            Request? request = JsonSerializer.Deserialize<Request>(line ?? "");
            if (request is null || !AllowedCommands.Contains(request.command ?? "")) return new(64, "unsupported command");
            string[] arguments = request.arguments ?? Array.Empty<string>();
            if (arguments.Length > 2 || arguments.Any(x => x.Length > 4096 || x.Contains('\0'))) return new(64, "invalid arguments");
            string command = request.command!.ToLowerInvariant();
            int expected = command switch { "configure" or "backup" or "update" => 1, "restore" => 2, "logs" => -1, _ => 0 };
            if ((expected >= 0 && arguments.Length != expected) || (command == "logs" && arguments.Length > 1))
                return new(64, "invalid argument count");
            if (command == "logs" && arguments.Length == 1 && (!int.TryParse(arguments[0], out int lines) || lines < 1 || lines > 5000))
                return new(64, "log line count must be within 1..5000");
            if (new[] { "configure", "backup", "restore", "update" }.Contains(command))
                for (int index = 0; index < arguments.Length; index++) arguments[index] = await WindowsPathToWsl(arguments[index], cancellation);
            return await RunWslAsync(command, arguments, cancellation);
        }
        catch (JsonException) { return new(64, "invalid request"); }
        catch (Exception ex) { return new(1, ex.Message.Length <= 500 ? ex.Message : ex.GetType().Name); }
    }

    private static async Task<string> WindowsPathToWsl(string path, CancellationToken cancellation)
    {
        string full = Path.GetFullPath(path);
        Response response = await RunProcess(new[] { "-d", Distro, "-u", "root", "--", "wslpath", "-a", full }, cancellation);
        if (response.exitCode != 0) throw new InvalidOperationException("could not map Windows path into WSL");
        return response.output.Trim();
    }

    private static Task<Response> RunWslAsync(string command, string[] arguments, CancellationToken cancellation)
    {
        var values = new List<string> { "-d", Distro, "-u", "root", "--", "/opt/finfusion/bin/node-control", command };
        values.AddRange(arguments);
        return RunProcess(values, cancellation);
    }

    private static async Task<Response> RunProcess(IEnumerable<string> arguments, CancellationToken cancellation)
    {
        var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "wsl.exe"))
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (string value in arguments) start.ArgumentList.Add(value);
        using var process = Process.Start(start) ?? throw new InvalidOperationException("could not start wsl.exe");
        Task<string> output = process.StandardOutput.ReadToEndAsync(cancellation);
        Task<string> error = process.StandardError.ReadToEndAsync(cancellation);
        await process.WaitForExitAsync(cancellation);
        string combined = (await output) + (await error);
        if (combined.Length > 1024 * 1024) combined = combined[^(1024 * 1024)..];
        return new(process.ExitCode, combined.TrimEnd());
    }

    private static async Task<int> RunClient(string command, string[] arguments)
    {
        using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut, PipeOptions.WriteThrough, TokenImpersonationLevel.Identification);
        try { await pipe.ConnectAsync(5000); }
        catch (TimeoutException) { Console.Error.WriteLine("Finfusion Node Host service is unavailable"); return 69; }
        using var writer = new StreamWriter(pipe, new UTF8Encoding(false), 8192, leaveOpen: true) { AutoFlush = true };
        using var reader = new StreamReader(pipe, new UTF8Encoding(false), false, 8192, leaveOpen: true);
        await writer.WriteLineAsync(JsonSerializer.Serialize(new Request(command, arguments)));
        Response? response = JsonSerializer.Deserialize<Response>(await reader.ReadLineAsync() ?? "");
        if (response is null) return 70;
        (response.exitCode == 0 ? Console.Out : Console.Error).WriteLine(response.output);
        return response.exitCode;
    }

    private static void EventLogWrite(string message)
    {
        try { File.AppendAllText(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "Finfusion", "node-host.log"), DateTimeOffset.UtcNow + " " + message + Environment.NewLine); } catch { }
    }

    private record Request(string? command, string[]? arguments);
    private record Response(int exitCode, string output);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ServiceTableEntry { [MarshalAs(UnmanagedType.LPWStr)] public string? name; public ServiceMainDelegate? callback; }
    [StructLayout(LayoutKind.Sequential)]
    private struct ServiceStatus { public int serviceType, currentState, controlsAccepted, win32ExitCode, serviceSpecificExitCode, checkPoint, waitHint; }
    private delegate void ServiceMainDelegate(int argc, IntPtr argv);
    private delegate int HandlerDelegate(int control, int eventType, IntPtr eventData, IntPtr context);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool StartServiceCtrlDispatcher(ServiceTableEntry[] table);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr RegisterServiceCtrlHandlerEx(string serviceName, HandlerDelegate callback, IntPtr context);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool SetServiceStatus(IntPtr handle, ref ServiceStatus status);
}
