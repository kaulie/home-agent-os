"""Amap (高德) route estimation for kind=system map.route.estimate.

Requires AMAP_WEB_KEY in environment. Geocodes place names then queries
direction APIs. No LLM fallback — API errors surface as capability failures.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("map_route")

AMAP_BASE = "https://restapi.amap.com/v3"
DEFAULT_CITY = "北京"
DEFAULT_TIMEOUT_SEC = 15.0

_MODE_ALIASES = {
    "driving": "driving",
    "drive": "driving",
    "car": "driving",
    "驾车": "driving",
    "开车": "driving",
    "自驾": "driving",
    "transit": "transit",
    "metro": "transit",
    "subway": "transit",
    "公交": "transit",
    "地铁": "transit",
    "公共交通": "transit",
    "walking": "walking",
    "walk": "walking",
    "步行": "walking",
    "走路": "walking",
}

_MODE_LABEL = {
    "driving": "驾车",
    "transit": "公共交通",
    "walking": "步行",
}


class MapRouteError(Exception):
    pass


def amap_web_key() -> str:
    for name in ("AMAP_WEB_KEY", "AMAP_KEY", "GAODE_WEB_KEY"):
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    raise MapRouteError("未配置高德 Web 服务 Key（AMAP_WEB_KEY）")


def _http_get(path: str, params: dict[str, str], *, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None and str(v) != ""})
    url = f"{AMAP_BASE}{path}?{q}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise MapRouteError(f"高德 API HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise MapRouteError(f"高德 API 不可达：{e.reason}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise MapRouteError("高德 API 返回非 JSON") from e
    if not isinstance(data, dict):
        raise MapRouteError("高德 API 返回格式错误")
    return data


def _api_ok(data: dict[str, Any]) -> bool:
    return str(data.get("status") or "").strip() == "1"


def _api_info(data: dict[str, Any]) -> str:
    return str(data.get("info") or data.get("infocode") or "未知错误").strip()


def normalize_mode(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "driving"
    if text in _MODE_ALIASES:
        return _MODE_ALIASES[text]
    for key, mode in _MODE_ALIASES.items():
        if key in text:
            return mode
    raise MapRouteError(f"不支持的出行方式：{raw}（可用 driving / transit / walking）")


def geocode_place(address: str, *, city: str | None = None, key: str | None = None) -> tuple[float, float]:
    addr = str(address or "").strip()
    if not addr:
        raise MapRouteError("起点或终点地址不能为空")
    api_key = key or amap_web_key()
    params = {"address": addr, "key": api_key, "output": "JSON"}
    city_text = str(city or "").strip()
    if city_text:
        params["city"] = city_text
    data = _http_get("/geocode/geo", params)
    if not _api_ok(data):
        raise MapRouteError(f"地址解析失败（{addr}）：{_api_info(data)}")
    geocodes = data.get("geocodes")
    if not isinstance(geocodes, list) or not geocodes:
        raise MapRouteError(f"找不到地址：{addr}")
    first = geocodes[0] if isinstance(geocodes[0], dict) else {}
    loc = str(first.get("location") or "").strip()
    if "," not in loc:
        raise MapRouteError(f"地址坐标无效：{addr}")
    lng_s, lat_s = loc.split(",", 1)
    try:
        return float(lng_s), float(lat_s)
    except ValueError as e:
        raise MapRouteError(f"地址坐标无效：{addr}") from e


def _format_distance(meters: int) -> str:
    if meters >= 1000:
        km = meters / 1000.0
        if km >= 10:
            return f"{km:.0f} 公里"
        return f"{km:.1f} 公里"
    return f"{meters} 米"


def _format_duration(seconds: int) -> str:
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec} 秒"
    minutes = sec // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rem = divmod(minutes, 60)
    if rem == 0:
        return f"{hours} 小时"
    return f"{hours} 小时 {rem} 分钟"


def _parse_int(raw: Any) -> int:
    try:
        return int(float(str(raw or "0").strip() or "0"))
    except (TypeError, ValueError):
        return 0


def _route_driving(origin: str, destination: str, *, key: str) -> tuple[int, int]:
    data = _http_get(
        "/direction/driving",
        {"origin": origin, "destination": destination, "key": key, "extensions": "base"},
    )
    if not _api_ok(data):
        raise MapRouteError(f"驾车路线查询失败：{_api_info(data)}")
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    paths = route.get("paths") if isinstance(route.get("paths"), list) else []
    if not paths or not isinstance(paths[0], dict):
        raise MapRouteError("驾车路线无结果")
    path = paths[0]
    return _parse_int(path.get("distance")), _parse_int(path.get("duration"))


def _route_walking(origin: str, destination: str, *, key: str) -> tuple[int, int]:
    data = _http_get(
        "/direction/walking",
        {"origin": origin, "destination": destination, "key": key},
    )
    if not _api_ok(data):
        raise MapRouteError(f"步行路线查询失败：{_api_info(data)}")
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    paths = route.get("paths") if isinstance(route.get("paths"), list) else []
    if not paths or not isinstance(paths[0], dict):
        raise MapRouteError("步行路线无结果")
    path = paths[0]
    return _parse_int(path.get("distance")), _parse_int(path.get("duration"))


def _route_transit(origin: str, destination: str, *, city: str, key: str) -> tuple[int, int]:
    data = _http_get(
        "/direction/transit/integrated",
        {
            "origin": origin,
            "destination": destination,
            "city": city,
            "key": key,
            "strategy": "0",
        },
    )
    if not _api_ok(data):
        raise MapRouteError(f"公共交通路线查询失败：{_api_info(data)}")
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    transits = route.get("transits") if isinstance(route.get("transits"), list) else []
    if not transits or not isinstance(transits[0], dict):
        raise MapRouteError("公共交通路线无结果")
    best = transits[0]
    return _parse_int(best.get("distance")), _parse_int(best.get("duration"))


def estimate_route(
    *,
    origin: str,
    destination: str,
    mode: str = "driving",
    city: str | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    """Geocode two place names and return distance/duration + spoken answer_text."""
    api_key = key or amap_web_key()
    mode_norm = normalize_mode(mode)
    city_text = str(city or "").strip() or DEFAULT_CITY
    origin_name = str(origin or "").strip()
    dest_name = str(destination or "").strip()
    if not origin_name or not dest_name:
        raise MapRouteError("origin 与 destination 均必填")

    o_lng, o_lat = geocode_place(origin_name, city=city_text, key=api_key)
    d_lng, d_lat = geocode_place(dest_name, city=city_text, key=api_key)
    origin_loc = f"{o_lng},{o_lat}"
    dest_loc = f"{d_lng},{d_lat}"

    if mode_norm == "driving":
        distance_m, duration_sec = _route_driving(origin_loc, dest_loc, key=api_key)
    elif mode_norm == "walking":
        distance_m, duration_sec = _route_walking(origin_loc, dest_loc, key=api_key)
    else:
        distance_m, duration_sec = _route_transit(
            origin_loc, dest_loc, city=city_text, key=api_key
        )

    if distance_m <= 0 and duration_sec <= 0:
        raise MapRouteError("路线结果为空")

    mode_label = _MODE_LABEL.get(mode_norm, mode_norm)
    dist_text = _format_distance(distance_m)
    dur_text = _format_duration(duration_sec)
    answer_text = (
        f"从{origin_name}到{dest_name}，{mode_label}大约 {dist_text}，"
        f"预计需要 {dur_text}。"
    )
    duration_min = max(1, (duration_sec + 59) // 60) if duration_sec > 0 else 0
    distance_km = f"{distance_m / 1000.0:.2f}" if distance_m > 0 else "0"

    log.info(
        "map.route.estimate mode=%s origin=%s dest=%s distance_m=%s duration_sec=%s",
        mode_norm,
        origin_name,
        dest_name,
        distance_m,
        duration_sec,
    )
    return {
        "answer_text": answer_text,
        "distance_m": str(distance_m),
        "distance_km": distance_km,
        "duration_sec": str(duration_sec),
        "duration_min": str(duration_min),
        "mode": mode_norm,
        "origin": origin_name,
        "destination": dest_name,
    }


def route_from_params(params: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    raw = params if isinstance(params, dict) else {}
    origin = str(raw.get("origin") or raw.get("from") or raw.get("start") or "").strip()
    destination = str(
        raw.get("destination") or raw.get("to") or raw.get("end") or raw.get("dest") or ""
    ).strip()
    mode = str(raw.get("mode") or raw.get("travel_mode") or "driving").strip()
    city = str(raw.get("city") or "").strip() or None
    outputs = estimate_route(origin=origin, destination=destination, mode=mode, city=city)
    msg = (
        f"map.route.estimate {outputs['mode']} "
        f"{outputs['distance_km']}km {outputs['duration_min']}min"
    )
    return msg, outputs
