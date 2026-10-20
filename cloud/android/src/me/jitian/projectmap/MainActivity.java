package me.jitian.projectmap;

import android.app.Activity;
import android.content.Intent;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.pm.ApplicationInfo;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final String ORIGIN = "https://appassets.androidplatform.net/";
    private WebView web;
    private final ExecutorService network = Executors.newFixedThreadPool(2);
    private ValueCallback<Uri[]> fileChooser;
    private byte[] exportData;
    private LoginVault loginVault;

    private boolean debugging() { return (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0; }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        loginVault = new LoginVault(this);
        WebView.setWebContentsDebuggingEnabled(debugging());
        web = new WebView(this);
        setContentView(web);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportZoom(false);
        web.addJavascriptInterface(new Bridge(), "AndroidBridge");
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (!"https".equals(uri.getScheme()) || !"appassets.androidplatform.net".equals(uri.getHost())) return null;
                String path = uri.getPath();
                if (path == null || path.contains("..") || path.contains("\\")) return blocked();
                try {
                    String relative = path.equals("/") ? "index.html" : path.substring(1);
                    String mime = relative.endsWith(".js") ? "text/javascript" : relative.endsWith(".css") ? "text/css" : relative.endsWith(".svg") ? "image/svg+xml" : "text/html";
                    Map<String,String> headers = new HashMap<>();
                    headers.put("Cache-Control", "no-cache");
                    headers.put("X-Content-Type-Options", "nosniff");
                    headers.put("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'");
                    return new WebResourceResponse(mime, "UTF-8", 200, "OK", headers, getAssets().open("web/" + relative));
                } catch (Exception error) { return blocked(); }
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (url.startsWith(ORIGIN)) return false;
                if (url.startsWith("https://") || url.startsWith("http://")) openExternal(url);
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileChooser != null) fileChooser.onReceiveValue(null);
                fileChooser = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                String[] types = params.getAcceptTypes();
                if (types.length == 1 && types[0].startsWith("image")) intent.setType("image/*");
                try { startActivityForResult(intent, 101); }
                catch (Exception error) { fileChooser.onReceiveValue(null); fileChooser=null; notice("未找到文件选择器"); }
                return true;
            }
        });
        web.loadUrl(ORIGIN + "index.html");
    }

    private WebResourceResponse blocked() {
        return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", new HashMap<>(), new java.io.ByteArrayInputStream(new byte[0]));
    }

    private void notice(String message) { runOnUiThread(() -> Toast.makeText(this, message, Toast.LENGTH_LONG).show()); }

    private void openExternal(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (Exception error) { notice("未找到可打开链接的应用"); }
    }

    private void respond(String id, int status, JSONObject body) {
        try {
            JSONObject response = new JSONObject().put("status",status).put("body",body);
            String script = "window.receiveNativeReply(" + JSONObject.quote(id) + "," + response.toString() + ")";
            runOnUiThread(() -> web.evaluateJavascript(script, null));
        } catch (Exception error) { notice("响应处理失败，本地内容仍保留"); }
    }

    private byte[] bounded(InputStream stream, int limit) throws Exception {
        try (InputStream input=stream; ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[16384];int count;
            while((count=input.read(buffer))!=-1) {if(output.size()+count>limit)throw new Exception("数据超过大小限制");output.write(buffer,0,count);}
            return output.toByteArray();
        }
    }

    public final class Bridge {
        @JavascriptInterface public String readLogin(String endpoint) {
            try { return loginVault.read(endpoint); }
            catch (Exception error) { return "{\"error\":\"自动登录信息无法读取，请重新登录\"}"; }
        }
        @JavascriptInterface public boolean saveLogin(String endpoint, String account) {
            try { return loginVault.save(endpoint, account); }
            catch (Exception error) { return false; }
        }
        @JavascriptInterface public boolean clearLogin(String endpoint) {
            try { return loginVault.clear(endpoint); }
            catch (Exception error) { return false; }
        }
        @JavascriptInterface public String readClipboardContent() {
            JSONObject result=new JSONObject();
            try {
                ClipboardManager clipboard=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
                ClipData clip=clipboard.getPrimaryClip();
                org.json.JSONArray images=new org.json.JSONArray();
                result.put("text","");result.put("images",images);
                if(clip!=null&&clip.getItemCount()>0) {
                    ClipData.Item item=clip.getItemAt(0);
                    if(item.getText()!=null)result.put("text",item.getText().toString());
                    Uri uri=item.getUri();
                    if(uri!=null&&"content".equals(uri.getScheme())) {
                        String mime=getContentResolver().getType(uri);
                        if(mime!=null&&mime.startsWith("image/")) {
                            InputStream input=getContentResolver().openInputStream(uri);
                            if(input!=null)images.put(new JSONObject().put("name","粘贴图片").put("mime",mime).put("data",Base64.encodeToString(bounded(input,12*1024*1024),Base64.NO_WRAP)));
                        }
                    }
                }
            } catch(Exception error){try{result.put("error","无法读取剪贴板，请使用插入图片或系统粘贴");}catch(Exception ignored){}}
            return result.toString();
        }
        @JavascriptInterface public void writeClipboard(String text) {
            runOnUiThread(()->{ClipboardManager clipboard=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);clipboard.setPrimaryClip(ClipData.newPlainText("项目航图",text));});
        }
        @JavascriptInterface public void request(String id,String endpoint,String method,String path,String body,String token) {
            network.execute(() -> {
                HttpURLConnection connection=null;
                try {
                    URL base=new URL(endpoint);
                    boolean localDebug = debugging() && "http".equals(base.getProtocol()) && ("127.0.0.1".equals(base.getHost()) || "localhost".equals(base.getHost()));
                    if((!"https".equals(base.getProtocol()) && !localDebug) || base.getUserInfo()!=null || !path.matches("api/[a-zA-Z0-9/?=&_\\-]+") || !(method.equals("GET")||method.equals("POST"))) throw new Exception("服务器地址或接口无效");
                    connection=(HttpURLConnection)new URL(endpoint+path).openConnection();
                    connection.setInstanceFollowRedirects(false);
                    connection.setConnectTimeout(12000);connection.setReadTimeout(25000);connection.setRequestMethod(method);
                    connection.setRequestProperty("Content-Type","application/json");
                    if(!token.isEmpty())connection.setRequestProperty("Authorization","Bearer "+token);
                    if(method.equals("POST")){
                        byte[] data=body.getBytes(StandardCharsets.UTF_8);if(data.length>18*1024*1024)throw new Exception("请求过大");
                        connection.setDoOutput(true);connection.setFixedLengthStreamingMode(data.length);try(OutputStream output=connection.getOutputStream()){output.write(data);}
                    }
                    int status=connection.getResponseCode();InputStream input=status>=400?connection.getErrorStream():connection.getInputStream();
                    if(input==null)throw new Exception("服务器未返回数据");
                    JSONObject result=new JSONObject(new String(bounded(input,20*1024*1024),StandardCharsets.UTF_8));respond(id,status,result);
                } catch(Exception error){try{respond(id,503,new JSONObject().put("error","连接失败，本地内容已保留："+error.getMessage()));}catch(Exception ignored){}}
                finally{if(connection!=null)connection.disconnect();}
            });
        }
        @JavascriptInterface public void exportFile(String name,String mime,String data) {
            try {
                byte[] bytes=Base64.decode(data,Base64.DEFAULT);if(bytes.length>100*1024*1024)throw new Exception("备份过大");
                runOnUiThread(() -> {
                    if(exportData!=null){notice("请先完成上一次导出");return;}exportData=bytes;
                    Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType(mime);intent.putExtra(Intent.EXTRA_TITLE,name);
                    try{startActivityForResult(intent,102);}catch(Exception error){exportData=null;notice("未找到文件保存器");}
                });
            } catch(Exception error){notice("导出失败："+error.getMessage());}
        }
    }

    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request==101 && fileChooser!=null){
            Uri[] files=null;
            if(result==RESULT_OK && data!=null){
                if(data.getClipData()!=null){int count=data.getClipData().getItemCount();files=new Uri[count];for(int i=0;i<count;i++)files[i]=data.getClipData().getItemAt(i).getUri();}
                else if(data.getData()!=null)files=new Uri[]{data.getData()};
            }
            fileChooser.onReceiveValue(files);fileChooser=null;
        }
        if(request==102 && exportData!=null){
            final byte[] bytes=exportData;exportData=null;
            if(result==RESULT_OK && data!=null && data.getData()!=null){final Uri uri=data.getData();network.execute(()->{try(OutputStream output=getContentResolver().openOutputStream(uri)){if(output==null)throw new Exception("无法打开目标文件");output.write(bytes);notice("已导出");}catch(Exception error){notice("导出失败："+error.getMessage());}});}
        }
    }
    @Override public void onBackPressed() {web.evaluateJavascript("(()=>{let d=document.querySelector('dialog[open]');if(d){d.close();return true;}let w=document.querySelector('#workspace');if(!w.classList.contains('no-library')){document.querySelector('#toggleLibrary').click();return true;}if(!w.classList.contains('no-assistant')){document.querySelector('#toggleAssistant').click();return true;}return false;})()",value->{if(!"true".equals(value))MainActivity.super.onBackPressed();});}
    @Override protected void onPause(){web.evaluateJavascript("window.pauseProjectMap&&window.pauseProjectMap()",null);super.onPause();}
    @Override protected void onResume(){super.onResume();if(web!=null)web.evaluateJavascript("window.resumeProjectMap&&window.resumeProjectMap()",null);}
    @Override protected void onDestroy(){network.shutdownNow();web.destroy();super.onDestroy();}
}
