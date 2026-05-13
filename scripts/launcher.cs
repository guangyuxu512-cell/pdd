using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace TaobaoToolboxLauncher
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string script = Path.Combine(root, "scripts", "start_portable.ps1");
            if (!File.Exists(script))
            {
                MessageBox.Show("启动脚本不存在：" + script, "淘宝工具箱", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = "powershell.exe";
            info.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\" -Port 8800";
            info.WorkingDirectory = root;
            info.UseShellExecute = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;

            try
            {
                Process.Start(info);
            }
            catch (Exception ex)
            {
                MessageBox.Show("启动失败：" + ex.Message, "淘宝工具箱", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
