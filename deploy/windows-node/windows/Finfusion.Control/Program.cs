using System.IO.Pipes;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace Finfusion.ServerControl;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new ControlForm());
    }
}

internal sealed class ControlForm : Form
{
    private readonly TextBox _output = new();
    private readonly Label _state = new();
    private readonly List<Control> _actions = new();

    public ControlForm()
    {
        Text = "Finfusion Server Control";
        MinimumSize = new Size(820, 560);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Segoe UI", 9F);

        var header = new Label {
            Text = "Finfusion 轻量服务器节点",
            Font = new Font("Segoe UI Semibold", 16F),
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 4),
        };
        _state.Text = "尚未读取状态";
        _state.AutoSize = true;
        _state.ForeColor = Color.DimGray;

        var commands = new FlowLayoutPanel {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            WrapContents = true,
            Padding = new Padding(0, 8, 0, 8),
        };
        AddButton(commands, "刷新状态", () => Execute("status"));
        AddButton(commands, "配置节点…", Configure);
        AddButton(commands, "启动", () => Execute("start"));
        AddButton(commands, "停止", () => Execute("stop", confirm: "停止服务并清除内存中的明文 Vault？"));
        AddButton(commands, "重启", () => Execute("restart", confirm: "重启会关闭节点激活和全局交易，继续？"));
        AddButton(commands, "激活节点", () => Execute("activate", confirm: "确认基础设施、对账及风险配置均已人工检查？"));
        AddButton(commands, "停用节点", () => Execute("deactivate"));
        AddButton(commands, "备份…", Backup);
        AddButton(commands, "恢复…", Restore);
        AddButton(commands, "诊断", () => Execute("doctor"));
        AddButton(commands, "最近日志", () => Execute("logs", ["200"]));
        AddButton(commands, "应用更新…", UpdateNode);

        _output.Dock = DockStyle.Fill;
        _output.Multiline = true;
        _output.ReadOnly = true;
        _output.ScrollBars = ScrollBars.Both;
        _output.WordWrap = false;
        _output.BackColor = Color.FromArgb(248, 249, 250);
        _output.Font = new Font("Consolas", 9F);
        _output.AccessibleName = "命令输出";

        var layout = new TableLayoutPanel {
            Dock = DockStyle.Fill,
            Padding = new Padding(20),
            ColumnCount = 1,
            RowCount = 4,
        };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 116));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.Controls.Add(header, 0, 0);
        layout.Controls.Add(_state, 0, 1);
        layout.Controls.Add(commands, 0, 2);
        layout.Controls.Add(_output, 0, 3);
        Controls.Add(layout);
        Shown += async (_, _) => await Execute("status");
    }

    private void AddButton(Control parent, string text, Func<Task> action)
    {
        var button = new Button { Text = text, AutoSize = true, Height = 34, Margin = new Padding(0, 0, 8, 8) };
        button.Click += async (_, _) => await action();
        parent.Controls.Add(button);
        _actions.Add(button);
    }

    private Task Configure()
    {
        using var dialog = new OpenFileDialog { Filter = "Finfusion 配置 (*.json)|*.json", CheckFileExists = true, Title = "选择节点配置文件" };
        return dialog.ShowDialog(this) == DialogResult.OK
            ? Execute("configure", [dialog.FileName], "配置会重新密封 Vault 并保持交易关闭，继续？")
            : Task.CompletedTask;
    }

    private Task Backup()
    {
        using var dialog = new SaveFileDialog { Filter = "Finfusion 加密 Vault (*.age)|*.age", DefaultExt = "age", AddExtension = true, Title = "保存 age 加密节点备份" };
        return dialog.ShowDialog(this) == DialogResult.OK ? Execute("backup", [dialog.FileName]) : Task.CompletedTask;
    }

    private Task Restore()
    {
        using var vaultDialog = new OpenFileDialog { Filter = "Finfusion 加密 Vault (*.age)|*.age", CheckFileExists = true, Title = "选择加密备份 Vault" };
        if (vaultDialog.ShowDialog(this) != DialogResult.OK) return Task.CompletedTask;
        using var identityDialog = new OpenFileDialog { Filter = "age identity (*.txt;*.key)|*.txt;*.key|所有文件 (*.*)|*.*", CheckFileExists = true, Title = "选择保存在节点外的 age identity" };
        return identityDialog.ShowDialog(this) == DialogResult.OK
            ? Execute("restore", [vaultDialog.FileName, identityDialog.FileName], "恢复会先完整验证密文，再停用节点并事务化替换两个数据库、Vault 与券商令牌。确认继续？")
            : Task.CompletedTask;
    }

    private Task UpdateNode()
    {
        using var dialog = new OpenFileDialog { Filter = "签名更新包 (*.tar.gz)|*.tar.gz", CheckFileExists = true, Title = "选择已签名更新包" };
        return dialog.ShowDialog(this) == DialogResult.OK
            ? Execute("update", [dialog.FileName], "更新会先停用节点并验证签名和哈希。确认继续？")
            : Task.CompletedTask;
    }

    private async Task Execute(string command, string[]? arguments = null, string? confirm = null)
    {
        if (confirm is not null && MessageBox.Show(this, confirm, "Finfusion Server Control", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
            return;
        SetBusy(true, $"正在执行 {command}…");
        try
        {
            PipeResponse response = await NodePipeClient.SendAsync(command, arguments ?? []);
            _output.Text = response.output;
            _state.Text = response.exitCode == 0 ? $"{command} 完成" : $"{command} 失败（退出码 {response.exitCode}）";
            _state.ForeColor = response.exitCode == 0 ? Color.DarkGreen : Color.DarkRed;
        }
        catch (Exception exception)
        {
            _output.Text = "无法连接 Finfusion Node Host。请以管理员身份运行并确认服务已启动。";
            _state.Text = $"操作失败：{exception.GetType().Name}";
            _state.ForeColor = Color.DarkRed;
        }
        finally { SetBusy(false); }
    }

    private void SetBusy(bool busy, string? text = null)
    {
        foreach (Control control in _actions) control.Enabled = !busy;
        UseWaitCursor = busy;
        if (text is not null) _state.Text = text;
    }
}

internal static class NodePipeClient
{
    private const string PipeName = "Finfusion.NodeControl.v1";

    public static async Task<PipeResponse> SendAsync(string command, string[] arguments)
    {
        using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut, PipeOptions.Asynchronous, TokenImpersonationLevel.Identification);
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(20));
        await pipe.ConnectAsync(5000, timeout.Token);
        using var writer = new StreamWriter(pipe, new UTF8Encoding(false), 8192, leaveOpen: true) { AutoFlush = true };
        using var reader = new StreamReader(pipe, new UTF8Encoding(false), false, 8192, leaveOpen: true);
        await writer.WriteLineAsync(JsonSerializer.Serialize(new PipeRequest(command, arguments)));
        string line = await reader.ReadLineAsync(timeout.Token) ?? throw new IOException("empty service response");
        return JsonSerializer.Deserialize<PipeResponse>(line) ?? throw new IOException("invalid service response");
    }

    private record PipeRequest(string command, string[] arguments);
}

internal record PipeResponse(int exitCode, string output);
