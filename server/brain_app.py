"""Brain entry: re-export the production app from home_brain.py.

Run (from repo root or server/):

  python home_brain.py
  python brain_app.py
"""

from home_brain import app, log

if __name__ == "__main__":
    try:
        import os

        from mdns_service import BRAIN_TYPE, lan_ipv4, publish_service, warm_img_server_discovery

        _BRAIN_MDNS = publish_service(
            name="Home Agent Brain",
            type_=BRAIN_TYPE,
            port=9527,
            txt={
                "role": "brain",
                "origin": os.environ.get("BRAIN_ORIGIN", "lan"),
                "lan_ip": lan_ipv4(),
            },
            hostname="brain.local",
        )
        # 启动即预热「资源服务器端口发现」（端点文件 → mDNS，后台线程）：
        # 第一条上传/取字节就能用上正确端口，而不必在请求路径上等 Bonjour。
        warm_img_server_discovery()
    except Exception:
        log.warning("mdns brain publish skipped; LAN discovery unavailable", exc_info=True)
    log.info("Brain home_brain.py on :9527")
    log.info("%s", app.url_map)
    app.run(host="0.0.0.0", port=9527, debug=False, use_reloader=False, threaded=True)
