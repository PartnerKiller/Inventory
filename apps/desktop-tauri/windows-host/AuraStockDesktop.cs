using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using System.Diagnostics;
using System.Security.Cryptography;

namespace AuraStock.Desktop
{
    public class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            string webDistDir = Path.Combine(appDir, "web");
            if (!Directory.Exists(webDistDir))
            {
                webDistDir = Path.Combine(appDir, "..", "web");
            }
            if (!Directory.Exists(webDistDir))
            {
                webDistDir = Path.Combine(appDir, "..", "..", "apps", "web", "dist");
            }

            int port = 4173;
            var server = new LocalAssetServer(webDistDir, port);
            server.Start();

            var mainForm = new MainWindow(port);
            Application.Run(mainForm);

            server.Stop();
        }
    }

    public class MainWindow : Form
    {
        private WebBrowser browser;
        private int port;

        public MainWindow(int serverPort)
        {
            this.port = serverPort;
            this.Text = "AuraStock Enterprise Inventory — Desktop Client v1.1.0";
            this.Width = 1440;
            this.Height = 900;
            this.StartPosition = FormStartPosition.CenterScreen;

            browser = new WebBrowser();
            browser.Dock = DockStyle.Fill;
            browser.ScriptErrorsSuppressed = true;
            browser.IsWebBrowserContextMenuEnabled = false;

            this.Controls.Add(browser);

            this.Load += (s, e) =>
            {
                browser.Navigate(string.Format("http://127.0.0.1:{0}/", this.port));
            };
        }
    }

    public class LocalAssetServer
    {
        private HttpListener listener;
        private string rootDir;
        private int port;
        private Thread listenerThread;
        private bool isRunning;

        public LocalAssetServer(string rootDirectory, int serverPort)
        {
            this.rootDir = rootDirectory;
            this.port = serverPort;
        }

        public void Start()
        {
            try
            {
                listener = new HttpListener();
                listener.Prefixes.Add(string.Format("http://127.0.0.1:{0}/", port));
                listener.Prefixes.Add(string.Format("http://localhost:{0}/", port));
                listener.Start();
                isRunning = true;

                listenerThread = new Thread(ListenLoop);
                listenerThread.IsBackground = true;
                listenerThread.Start();
            }
            catch (Exception ex)
            {
                Console.WriteLine("Server start note: " + ex.Message);
            }
        }

        public void Stop()
        {
            isRunning = false;
            try
            {
                if (listener != null && listener.IsListening)
                {
                    listener.Stop();
                    listener.Close();
                }
            }
            catch { }
        }

        private void ListenLoop()
        {
            while (isRunning && listener != null && listener.IsListening)
            {
                try
                {
                    var ctx = listener.GetContext();
                    ThreadPool.QueueUserWorkItem((state) => ProcessRequest(ctx));
                }
                catch
                {
                    if (!isRunning) break;
                }
            }
        }

        private void ProcessRequest(HttpListenerContext context)
        {
            try
            {
                string urlPath = context.Request.Url.AbsolutePath.TrimStart('/');
                if (string.IsNullOrEmpty(urlPath)) urlPath = "index.html";

                string filePath = Path.Combine(rootDir, urlPath.Replace('/', Path.DirectorySeparatorChar));
                if (!File.Exists(filePath))
                {
                    filePath = Path.Combine(rootDir, "index.html");
                }

                if (File.Exists(filePath))
                {
                    byte[] bytes = File.ReadAllBytes(filePath);
                    string ext = Path.GetExtension(filePath).ToLowerInvariant();
                    string mime = "application/octet-stream";
                    if (ext == ".html") mime = "text/html";
                    else if (ext == ".js") mime = "application/javascript";
                    else if (ext == ".css") mime = "text/css";
                    else if (ext == ".json") mime = "application/json";
                    else if (ext == ".png") mime = "image/png";
                    else if (ext == ".svg") mime = "image/svg+xml";

                    context.Response.ContentType = mime;
                    context.Response.ContentLength64 = bytes.Length;
                    context.Response.OutputStream.Write(bytes, 0, bytes.Length);
                }
                else
                {
                    context.Response.StatusCode = 404;
                }
            }
            catch { }
            finally
            {
                try { context.Response.OutputStream.Close(); } catch { }
            }
        }
    }
}
