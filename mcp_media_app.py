"""MCP Apps resource used to render Discord media tool results inline."""

from __future__ import annotations

from mcp.server.apps import Apps, ResourceCsp


MEDIA_UI_RESOURCE_URI = "ui://discord/media-viewer.html"

MEDIA_VIEWER_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Discord media</title>
  <style>
    :root { color-scheme: light dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 12px;
      font: 14px/1.4 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: transparent;
      color: CanvasText;
    }
    #card {
      border: 1px solid color-mix(in srgb, CanvasText 16%, transparent);
      border-radius: 14px;
      overflow: hidden;
      background: color-mix(in srgb, Canvas 96%, CanvasText 4%);
    }
    #header { padding: 10px 12px; border-bottom: 1px solid color-mix(in srgb, CanvasText 12%, transparent); }
    #title { font-weight: 650; }
    #meta { margin-top: 2px; opacity: .7; font-size: 12px; overflow-wrap: anywhere; }
    #gallery { display: grid; gap: 8px; padding: 10px; }
    img {
      display: block;
      width: 100%;
      max-height: 70vh;
      object-fit: contain;
      border-radius: 10px;
      background: color-mix(in srgb, CanvasText 5%, transparent);
    }
    #status { padding: 18px 12px; opacity: .7; text-align: center; }
  </style>
</head>
<body>
  <section id="card">
    <header id="header">
      <div id="title">Discord media</div>
      <div id="meta">Waiting for media…</div>
    </header>
    <div id="status">Loading…</div>
    <div id="gallery" hidden></div>
  </section>

  <script type="module">
    import { App } from "https://esm.sh/@modelcontextprotocol/ext-apps@1.7.5";

    const app = new App({ name: "Discord Media Viewer", version: "1.0.0" });
    const status = document.getElementById("status");
    const gallery = document.getElementById("gallery");
    const meta = document.getElementById("meta");
    function clearImages() {
      gallery.replaceChildren();
    }

    function render(result) {
      clearImages();
      const content = Array.isArray(result?.content) ? result.content : [];
      const text = content.find((item) => item?.type === "text")?.text;
      if (text) {
        try {
          const info = JSON.parse(text);
          const label = [info.filename, info.detected_kind, info.downloaded_bytes ? `${info.downloaded_bytes} bytes` : null]
            .filter(Boolean)
            .join(" · ");
          meta.textContent = label || "Discord attachment";
        } catch {
          meta.textContent = text.slice(0, 180);
        }
      } else {
        meta.textContent = "Discord attachment";
      }

      const images = content.filter((item) => item?.type === "image" && item?.data);
      if (!images.length) {
        status.hidden = false;
        status.textContent = "No renderable image frame was returned.";
        gallery.hidden = true;
        return;
      }

      for (const image of images) {
        const mime = image.mimeType || image.mime_type || "image/png";
        const element = document.createElement("img");
        // MCP Apps hosts are required to allow data: images, while blob: is not
        // guaranteed by the standard CSP. Keep the returned MCP ImageContent
        // bytes self-contained so the viewer works in strict hosts such as ChatGPT.
        element.src = `data:${mime};base64,${image.data}`;
        element.alt = "Discord media";
        gallery.appendChild(element);
      }

      status.hidden = true;
      gallery.hidden = false;
    }

    app.ontoolresult = render;
    app.connect().catch((error) => {
      status.hidden = false;
      status.textContent = `Widget connection failed: ${error?.message || error}`;
    });
  </script>
</body>
</html>
"""


def build_media_apps_extension() -> Apps:
    """Build the MCP Apps extension containing the Discord media viewer resource."""
    apps = Apps()
    apps.add_html_resource(
        MEDIA_UI_RESOURCE_URI,
        MEDIA_VIEWER_HTML,
        name="Discord media viewer",
        title="Discord media viewer",
        description="Render images and sampled GIF/video frames returned by Discord media tools.",
        csp=ResourceCsp(resource_domains=["https://esm.sh"]),
        prefers_border=True,
    )
    return apps
