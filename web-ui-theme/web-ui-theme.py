import os
import logging
import traceback
import pwnagotchi.plugins as plugins
from pwnagotchi import config

# Import Flask Response for proper header handling
from flask import Response

# Dynamic path detection based on pwnagotchi installation
import pwnagotchi

PWNAGOTCHI_PATH = os.path.dirname(os.path.dirname(pwnagotchi.__file__))
BASE_HTML = os.path.join(PWNAGOTCHI_PATH, "pwnagotchi/ui/web/templates/base.html")
PLUGIN_NAME = "web-ui-theme"


class WebUiTheme(plugins.Plugin):
    __author__ = "wsvdmeer"
    __version__ = "0.0.1"
    __description__ = "Theme manager for the Pwnagotchi Web UI"

    def __init__(self):
        super().__init__()
        self.ready = False

    def on_loaded(self):
        try:
            logging.info(f"[{PLUGIN_NAME}] Plugin loaded")
            self._unpatch_base_html()  # Remove any old version first
            self._patch_base_html()
            self.ready = True
            logging.info(f"[{PLUGIN_NAME}] Plugin initialization complete")
        except Exception as e:
            logging.error(f"[{PLUGIN_NAME}] Error during on_loaded: {e}")
            logging.error(f"[{PLUGIN_NAME}] Traceback: {traceback.format_exc()}")
            self.ready = False

    def on_unload(self):
        try:
            logging.info(f"[{PLUGIN_NAME}] Unloading plugin")
            self._unpatch_base_html()
            logging.info(f"[{PLUGIN_NAME}] Plugin unloaded successfully")
        except Exception as e:
            logging.error(f"[{PLUGIN_NAME}] Error during on_unload: {e}")
            logging.error(f"[{PLUGIN_NAME}] Traceback: {traceback.format_exc()}")

    # ─────────────────────────
    # Base.html patching
    # ─────────────────────────

    def _patch_base_html(self):
        try:
            if not os.path.exists(BASE_HTML):
                logging.warning(f"[{PLUGIN_NAME}] Base HTML not found at {BASE_HTML}")
                return

            with open(BASE_HTML, "r") as f:
                content = f.read()

            if PLUGIN_NAME in content:
                logging.debug(f"[{PLUGIN_NAME}] Base HTML already patched")
                return

            inject = (
                f"\n<!-- {PLUGIN_NAME} -->\n"
                f'<link id="web-ui-theme" rel="stylesheet" href="/plugins/web-ui-theme/current.css">\n'
            )

            content = content.replace("</head>", inject + "</head>")

            with open(BASE_HTML, "w") as f:
                f.write(content)

            # Write the current theme CSS file on first load
            self._write_current_css()
            logging.info(f"[{PLUGIN_NAME}] Base HTML patched successfully")
        except Exception as e:
            logging.error(f"[{PLUGIN_NAME}] Error patching base HTML: {e}")
            logging.error(f"[{PLUGIN_NAME}] Traceback: {traceback.format_exc()}")

    def _unpatch_base_html(self):
        try:
            if not os.path.exists(BASE_HTML):
                logging.warning(f"[{PLUGIN_NAME}] Base HTML not found at {BASE_HTML}")
                return

            with open(BASE_HTML, "r") as f:
                content = f.read()

            if PLUGIN_NAME not in content:
                logging.debug(
                    f"[{PLUGIN_NAME}] Base HTML not patched, nothing to remove"
                )
                return

            lines = [l for l in content.splitlines() if PLUGIN_NAME not in l]

            with open(BASE_HTML, "w") as f:
                f.write("\n".join(lines))
            logging.info(f"[{PLUGIN_NAME}] Base HTML unpatched successfully")
        except Exception as e:
            logging.error(f"[{PLUGIN_NAME}] Error unpatching base HTML: {e}")
            logging.error(f"[{PLUGIN_NAME}] Traceback: {traceback.format_exc()}")

    # ─────────────────────────
    # CSS file management
    # ─────────────────────────

    def _write_current_css(self):
        """Write the active theme's CSS to current.css"""
        try:
            theme = self._active_theme()
            current_file = os.path.join(self._themes_dir(), "current.css")

            # Default theme = empty CSS
            if theme == "default":
                with open(current_file, "w") as f:
                    f.write("")
                logging.debug(f"[{PLUGIN_NAME}] Set to default theme (empty CSS)")
                return

            # Load theme CSS file
            theme_file = os.path.join(self._themes_dir(), f"{theme}.css")
            if os.path.exists(theme_file):
                with open(theme_file, "r") as f:
                    css_content = f.read()
                with open(current_file, "w") as f:
                    f.write(css_content)
                logging.debug(f"[{PLUGIN_NAME}] Wrote {theme} to current.css")
            else:
                logging.warning(f"[{PLUGIN_NAME}] Theme file not found: {theme_file}")
        except Exception as e:
            logging.error(f"[{PLUGIN_NAME}] Error writing current.css: {e}")
            logging.error(f"[{PLUGIN_NAME}] Traceback: {traceback.format_exc()}")

    # ─────────────────────────
    # Theme handling
    # ─────────────────────────

    def _themes_dir(self):
        return os.path.join(os.path.dirname(__file__), "themes")

    def _available_themes(self):
        try:
            themes = sorted(
                f.replace(".css", "")
                for f in os.listdir(self._themes_dir())
                if f.endswith(".css") and f != "current.css"
            )
            themes.insert(0, "default")  # Add default as first option
            logging.debug(f"[{PLUGIN_NAME}] Available themes: {themes}")
            return themes
        except Exception as e:
            logging.error(f"[{PLUGIN_NAME}] Failed to list themes: {e}")
            return ["default"]

    def _active_theme(self):
        theme = config["main"]["plugins"][PLUGIN_NAME].get("theme", "dark")
        logging.debug(f"[{PLUGIN_NAME}] Active theme: {theme}")
        return theme

    # ─────────────────────────
    # Web UI routes
    # ─────────────────────────

    def on_webhook(self, path, request):
        try:
            # Normalize path - handle None
            if path is None:
                path = ""
            path = str(path).lstrip("/") if path else ""

            logging.debug(f"[{PLUGIN_NAME}] on_webhook called with path: '{path}'")

            # Serve current CSS file
            if path == "current.css":
                logging.debug(f"[{PLUGIN_NAME}] Serving current theme CSS")
                current_file = os.path.join(self._themes_dir(), "current.css")
                if os.path.exists(current_file):
                    with open(current_file, "r") as f:
                        return Response(
                            f.read(), content_type="text/css; charset=utf-8"
                        )
                logging.warning(f"[{PLUGIN_NAME}] current.css not found")
                return ""

            # Serve theme CSS
            if path.startswith("theme/"):
                name = path.split("/")[-1]
                css = os.path.join(self._themes_dir(), f"{name}.css")
                if os.path.exists(css):
                    logging.debug(f"[{PLUGIN_NAME}] Serving CSS for theme: {name}")
                    with open(css, "r") as f:
                        return Response(
                            f.read(), content_type="text/css; charset=utf-8"
                        )
                logging.warning(f"[{PLUGIN_NAME}] CSS file not found for theme: {name}")
                return ""

            # Change theme
            if path.startswith("set/"):
                theme = path.split("/")[-1]
                if theme in self._available_themes():
                    logging.info(f"[{PLUGIN_NAME}] Changing theme to: {theme}")
                    try:
                        config["main"]["plugins"][PLUGIN_NAME]["theme"] = theme
                        # Try to save config if method exists
                        if hasattr(config, "save") and callable(
                            getattr(config, "save")
                        ):
                            config.save()
                    except Exception as e:
                        logging.warning(f"[{PLUGIN_NAME}] Could not save config: {e}")
                    self._write_current_css()  # Update current.css
                else:
                    logging.warning(f"[{PLUGIN_NAME}] Invalid theme requested: {theme}")
                return "<script>location.href='/plugins/web-ui-theme'</script>"

            # Theme selector UI (root path)
            if path == "":
                logging.debug(f"[{PLUGIN_NAME}] Rendering theme selector UI")
                return self._render_selector()

            logging.warning(f"[{PLUGIN_NAME}] Unknown webhook path: '{path}'")
            return "Unknown path"
        except Exception as e:
            logging.error(f"[{PLUGIN_NAME}] Error in on_webhook: {e}")
            logging.error(f"[{PLUGIN_NAME}] Traceback: {traceback.format_exc()}")
            return f"Error: {e}"

    # ─────────────────────────
    # HTML UI
    # ─────────────────────────

    def _render_selector(self):
        active = self._active_theme()
        items = ""

        for t in self._available_themes():
            is_active = t == active
            button_text = "Active" if is_active else "Select"
            button_class = "success" if is_active else "default"
            items += f"""
            <div class="theme-item">
              <div style="flex: 1;">
                <b style="color: #d4d4d4; font-size: 16px;">{t.title()}</b>
              </div>
              <a href="/plugins/web-ui-theme/set/{t}" class="button {button_class}">
                {button_text}
              </a>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html>
          <head>
            <title>Web UI Themes</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <style>
              * {{ margin: 0; padding: 0; box-sizing: border-box; }}
              body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; 
                padding: 20px; 
                max-width: 600px; 
                margin: 0 auto; 
                background: #0d1117; 
                color: #d4d4d4;
                min-height: 100vh;
              }}
              h1 {{ 
                color: #58a6ff; 
                margin-bottom: 8px;
                font-size: 28px;
              }}
              .subtitle {{ 
                color: #8b949e;
                margin-bottom: 24px;
                font-size: 14px;
              }}
              .card {{ 
                background: #161b22; 
                padding: 24px; 
                border-radius: 8px; 
                border: 1px solid #30363d; 
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
                margin-bottom: 16px;
              }}
              .theme-item {{ 
                padding: 16px; 
                margin-bottom: 12px; 
                border: 1px solid #30363d; 
                border-radius: 6px; 
                display: flex; 
                justify-content: space-between; 
                align-items: center;
                background: #0d1117;
                transition: all 0.2s ease;
              }}
              .theme-item:hover {{ 
                background: #161b22; 
                border-color: #58a6ff;
              }}
              .button {{ 
                padding: 10px 20px; 
                text-decoration: none;
                border-radius: 4px; 
                cursor: pointer; 
                font-size: 14px; 
                font-weight: 600;
                border: 1px solid;
                transition: all 0.2s ease;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 36px;
              }}
              .button.default {{ 
                color: #58a6ff;
                border-color: #58a6ff;
                background: transparent;
              }}
              .button.default:hover {{ 
                background: rgba(88, 166, 255, 0.1);
                border-color: #79c0ff;
              }}
              .button.success {{ 
                color: #3fb950;
                border-color: #3fb950;
                background: transparent;
                cursor: default;
              }}
              .button.success:hover {{ 
                background: rgba(63, 185, 80, 0.1);
              }}
              .info-box {{
                background: rgba(88, 166, 255, 0.1);
                border: 1px solid #58a6ff;
                border-left: 4px solid #58a6ff;
                padding: 12px;
                border-radius: 4px;
                color: #79c0ff;
                font-size: 13px;
                margin-top: 12px;
              }}
              @media (max-width: 600px) {{
                body {{ padding: 16px; }}
                .card {{ padding: 16px; }}
                .theme-item {{ 
                  flex-direction: column; 
                  align-items: stretch;
                  gap: 12px;
                }}
                .button {{ width: 100%; }}
              }}
            </style>
          </head>
          <body>
            <div class="card">
              <h1>🎨 Web UI Themes</h1>
              <div class="subtitle">Select a theme to customize your Pwnagotchi web interface</div>
              
              <div>
                {items}
              </div>
              
              <div class="info-box">
                💡 Themes are applied instantly to the web UI. The current theme will be remembered on next visit.
              </div>
            </div>
          </body>
        </html>
        """
