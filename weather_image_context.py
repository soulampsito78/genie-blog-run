"""
Image-side weather context for today_genie (OpenWeather, same provider as tomorrow_genie).

Converts forecast summary into wardrobe/scene hints for bottom image generation only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


def _num(x: Any) -> float | None:
    if isinstance(x, (int, float)):
        return float(x)
    return None


def build_image_weather_context_for_today(
    weather_context: Dict[str, Any],
    kst_now: datetime,
) -> Dict[str, Any]:
    """
    Build image-safe weather bands from OpenWeather-shaped `weather_context`
    (output of main.fetch_seoul_weather_forecast) or empty dict.

    Never raises; always returns a dict usable by image_exec_suffixes / prompts.
    """
    if not weather_context or weather_context.get("provider") != "openweather":
        return _fallback_image_weather("no_openweather_payload", kst_now)

    summary = weather_context.get("summary")
    if not isinstance(summary, dict) or not summary:
        return _fallback_image_weather("empty_summary", kst_now)

    t_min = _num(summary.get("temp_min"))
    t_max = _num(summary.get("temp_max"))
    feels = _num(summary.get("feels_like_avg"))
    if feels is not None:
        ref = feels
    elif t_min is not None and t_max is not None:
        ref = (t_min + t_max) / 2.0
    elif t_max is not None:
        ref = t_max
    elif t_min is not None:
        ref = t_min
    else:
        return _fallback_image_weather("no_temperature", kst_now)

    pop_max = _num(summary.get("precipitation_probability_max"))
    wind_max = _num(summary.get("wind_speed_max"))  # OpenWeather m/s in 5/3h forecast
    humidity_avg = _num(summary.get("humidity_avg"))
    conditions = summary.get("conditions")
    cond_list: List[str] = []
    if isinstance(conditions, list):
        cond_list = [str(c) for c in conditions if isinstance(c, str)]

    low = " ".join(cond_list).lower()
    rainy = (pop_max is not None and pop_max >= 0.45) or any(
        k in low for k in ("rain", "drizzle", "shower", "storm", "snow", "비", "눈", "소나기")
    )

    band, outer, style, scene, wardrobe, avoid = _bands_from_temp(ref, rainy, wind_max)

    return {
        "source": "openweather",
        "reference_temp_c": round(ref, 1),
        "temp_min_c": round(t_min, 1) if t_min is not None else None,
        "temp_max_c": round(t_max, 1) if t_max is not None else None,
        "precipitation_probability_max": round(pop_max, 2) if pop_max is not None else None,
        "wind_speed_max_m_s": round(wind_max, 1) if wind_max is not None else None,
        "humidity_avg": round(humidity_avg, 1) if humidity_avg is not None else None,
        "conditions": cond_list,
        "weather_band": band,
        "outerwear_need": outer,
        "styling_group": style,
        "scene_hint": scene,
        "wardrobe_hint": wardrobe,
        "avoid_items": avoid,
    }


def _bands_from_temp(
    ref_c: float,
    rainy: bool,
    wind_max: float | None,
) -> tuple[str, str, str, str, str, list[str]]:
    """Return (weather_band, outerwear_need, styling_group, scene_hint, wardrobe_hint, avoid_items)."""
    breezy = wind_max is not None and wind_max >= 8.0

    if ref_c >= 28:
        band = "hot"
        outer = "none"
        style = "light_breathable"
        scene = "bright warm morning; shade or open air ok"
        wardrobe = "breathable dress, sleeveless or short sleeves, light skirt or linen pants; open shoes or light sneakers"
        avoid = ["trench coat", "wool coat", "padded jacket", "heavy knit", "scarf unless indoor AC"]
    elif ref_c >= 23:
        band = "warm"
        outer = "none_or_ultra_light"
        style = "smart_casual_light"
        scene = "pleasant warm morning urban commute"
        wardrobe = "dress, blouse, light trousers or skirt, light cardigan optional in shade"
        avoid = ["trench", "wool coat", "padded outerwear", "thick scarf"]
    elif ref_c >= 18:
        band = "mild_warm"
        outer = "light_optional"
        style = "smart_daily"
        scene = "mild Seoul morning; breathable layers"
        wardrobe = "blouse or knit top, trousers or midi skirt, light cardigan or unstructured jacket if needed"
        avoid = ["heavy parka", "padded coat", "thick winter scarf"]
    elif ref_c >= 12:
        band = "cool"
        outer = "light_jacket_or_trench_ok"
        style = "layered_smart"
        scene = "crisp cool morning; light breeze possible" + ("; breezy" if breezy else "")
        wardrobe = "light jacket, trench, or blazer; light scarf optional; closed shoes"
        avoid = ["summer beach look", "heavy padded parka unless ref clearly cold"]
    elif ref_c >= 6:
        band = "cold"
        outer = "warm_coat_allowed"
        style = "warm_layers"
        scene = "cold morning; layered urban outerwear"
        wardrobe = "wool coat, warm jacket, knit layers, scarf ok"
        avoid = ["sleeveless summer outfit"]
    else:
        band = "very_cold"
        outer = "heavy_outerwear_allowed"
        style = "winter_layers"
        scene = "very cold morning; insulated outerwear"
        wardrobe = "padded or heavy coat, warm knit, gloves/scarf as needed"
        avoid = ["thin summer dress as sole layer"]

    if rainy:
        scene += "; wet or showery — practical rain-aware styling"
        wardrobe += "; compact umbrella or water-resistant light outer layer if appropriate"
        avoid = list(avoid) + ["suede shoes in deep puddles", "delicate silk as only layer in rain"]

    return band, outer, style, scene, wardrobe, avoid


def _fallback_image_weather(reason: str, kst_now: datetime) -> Dict[str, Any]:
    """Conservative mild band when API fails — avoids heavy winter default."""
    _ = kst_now
    return {
        "source": "fallback",
        "fallback_reason": reason,
        "reference_temp_c": None,
        "temp_min_c": None,
        "temp_max_c": None,
        "precipitation_probability_max": None,
        "wind_speed_max_m_s": None,
        "conditions": [],
        "weather_band": "mild_unknown",
        "outerwear_need": "light_optional",
        "styling_group": "smart_casual_light",
        "scene_hint": "Seoul weekday morning; season-appropriate mild air (forecast unavailable—stay conservative)",
        "wardrobe_hint": "blouse or light knit, trousers or skirt, optional light cardigan; no heavy trench or padded coat unless clearly justified",
        "avoid_items": ["heavy parka", "padded winter coat", "thick scarf as default"],
    }
