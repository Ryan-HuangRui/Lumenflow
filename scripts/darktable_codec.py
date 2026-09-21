#!/usr/bin/env python3
"""Fail-closed darktable 5.4.1 XMP history/module codec.

darktable stores most module state as a binary C struct in the XMP history
stack.  This module intentionally supports only structs whose layout has been
checked against the 5.4.1 source and a real ``darktable-cli`` render.  Unknown
modules, fields and versions are rejected rather than being copied into an
XMP file optimistically.

The codec is deliberately independent from the execution planner.  It accepts
an existing XMP document (or builds a minimal one), appends/replaces selected
history entries, and returns the complete XMP text plus a list of the modules
that were actually encoded.  The caller remains responsible for binding the
document to a fingerprinted preview and for invoking darktable in an isolated
runtime.
"""

from __future__ import annotations

import base64
import binascii
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Mapping


CODEC_SCHEMA_VERSION = "lumenflow.darktable_codec.v2"
DARKTABLE_VERSION = "5.4.1"
DARKTABLE_XMP_VERSION = "5"
MULTI_PRIORITY_MIN = 0
MULTI_PRIORITY_MAX = 1000

DT_NS = "http://darktable.sf.net/"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XMP_NS = "http://ns.adobe.com/xap/1.0/"
XMP_MM_NS = "http://ns.adobe.com/xap/1.0/mm/"

ET.register_namespace("x", "adobe:ns:meta/")
ET.register_namespace("rdf", RDF_NS)
ET.register_namespace("darktable", DT_NS)
ET.register_namespace("xmp", XMP_NS)
ET.register_namespace("xmpMM", XMP_MM_NS)


class DarktableCodecError(ValueError):
    """Raised when a module request cannot be encoded safely."""


@dataclass(frozen=True)
class ModuleSpec:
    operation: str
    modversion: int
    template: bytes
    fields: Mapping[str, tuple[int, str, float | int | None, float | int | None]]
    integer_fields: frozenset[str] = frozenset()
    string_fields: Mapping[str, tuple[int, int]] | None = None  # byte offset, max UTF-8 bytes
    allowed_values: Mapping[str, frozenset[int]] | None = None
    one_instance: bool = False


def _hex(value: str) -> bytes:
    try:
        return bytes.fromhex(value)
    except ValueError as error:
        raise RuntimeError(f"invalid embedded darktable template: {value[:24]}") from error


# These templates are neutral/default module states captured from the
# darktable 5.4.1 bundled styles and checked with darktable-cli 5.4.1.  They
# are kept as hex so the repository does not depend on an installed app.
_EXPOSURE_V6 = _hex("00000000000080b96666663f00004842000080c000000000")
_EXPOSURE_V7 = struct.pack("<ifff fii", 0, -0.000244140625, 0.0, 50.0, -4.0, 0, 1)
_TEMPERATURE_V4 = struct.pack("<4fi", 1.0, 1.0, 1.0, -2.0, 2)
_SIGMOID_V3 = _hex(
    "0000c03f000000000000c8426c09793c000000000000c842"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
_COLORBALANCE_RGB_V5 = _hex(
    "0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000803f000000000000803f00000000"
    "000000000000000000000000c8cc4c3e00000000000000000000000000000000"
    "0000000000000000000000000000000091ed3c3ecccc4c3e91ed3c3e00000000"
    "01000000"
)
_FILMIC_RGB_V6 = _hex(
    "9a9993410000a0c0ffff7f4000000000000040400000c8420000c84200000000"
    "000000009a9993412fa6783c0000c8421d0638400ad7233c6566a63fffffefc1"
    "00000000cdcc4c3e030000000400000001000000000000000100000001000000"
    "0000000000000000000000000200000000000000"
)
_CROP_V3 = struct.pack("<4f2i", 0.0, 0.0, 1.0, 1.0, -1, -1)

# The following payloads are deliberately assembled from the exact 5.4.1
# structs rather than copied from a user sidecar.  The source layouts are
# pinned in docs/darktable_backend_spike.md and each payload is exercised by
# darktable-cli in the opt-in live test.
_HIGHLIGHTS_V4 = _hex(
    "050000000000803f00000000000000000000803f000000001e000000"
    "06000000cdcccc3e000000400000000000000000"
)
_DEMOSAIC_V6 = struct.pack(
    "<ifiiiffffifi",
    0,       # green_eq
    0.0,     # median_thrs
    0,       # color_smoothing
    5,       # RCD
    1,       # LMMSE median refine
    0.2,     # dual threshold
    0.0,     # capture sharpen radius
    0.4,     # capture sharpen threshold
    0.0,     # capture sharpen corner boost
    8,       # capture sharpen iterations
    0.0,     # capture sharpen center
    0,       # capture sharpen enabled
)


def _denoiseprofile_v12() -> bytes:
    # dt_iop_denoiseprofile_params_t v12: 8 scalar floats, a[3]/b[3],
    # mode, x[6][7], y[6][7], and five 32-bit flags/enums.
    data = bytearray(416)
    struct.pack_into("<8f", data, 0, 1.0, 7.0, 1.0, 1.0, 0.0, 0.0, 0.1, 1.0)
    # a[0] == -1 requests 5.4.1's image-profile autodetection.  This keeps
    # the template camera-neutral; callers can supply a measured profile in a
    # future codec revision once its source/schema contract is frozen.
    struct.pack_into("<6f", data, 32, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    struct.pack_into("<i", data, 56, 1)  # MODE_WAVELETS
    for channel in range(6):
        for band in range(7):
            index = channel * 7 + band
            struct.pack_into("<f", data, 60 + index * 4, band / 6.0)
            # The Y0 curve is neutral in the bundled 5.4.1 preset; chroma
            # curves retain the documented neutral 0.5 force.
            y = 0.0 if channel == 4 else 0.5
            struct.pack_into("<f", data, 228 + index * 4, y)
    struct.pack_into("<5i", data, 396, 1, 1, 1, 1, 0)
    return bytes(data)


def _lens_v10() -> bytes:
    # dt_iop_lens_params_t v10.  Camera/lens are intentionally empty until
    # explicitly supplied by the request; no bundled camera profile is used as
    # a generic base.
    data = bytearray(356)
    struct.pack_into(
        "<3iffff",
        data,
        0,
        0,       # embedded metadata method
        7,       # all correction flags
        0,       # correct (not inverse)
        1.0,     # scale
        1.0,     # crop
        0.0,     # focal from metadata
        0.0,     # aperture from metadata
    )
    struct.pack_into("<f", data, 28, 1000.0)  # focus distance fallback
    struct.pack_into("<i", data, 32, 0)       # rectilinear target geometry
    struct.pack_into("<i", data, 292, 0)  # tca override
    struct.pack_into("<2f", data, 296, 1.0, 1.0)
    struct.pack_into("<4f", data, 304, 1.0, 1.0, 1.0, 1.0)
    struct.pack_into("<fif", data, 320, 1.0, 0, 1.0)
    struct.pack_into("<i", data, 332, 1)
    struct.pack_into("<3f", data, 336, 0.0, 0.5, 0.5)
    return bytes(data)


_SHARPEN_V1 = struct.pack("<3f", 2.0, 0.5, 0.5)
_DIFFUSE_V2 = _hex(
    "1e0000000000000002000000ffffbf3fc0cc4cbd00000000"
    "feff3f4000000000000000000000000000d7a33c00d7233d"
    "90c2f5bd00d7233d00000000"
)
_TONEEQUAL_V2 = struct.pack(
    "<15f3i",
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    5.0, 2**0.5, 1.0, 0.0, 0.0, 0.0,
    0, 2, 1,
)


def _colorequal_v4() -> bytes:
    data = bytearray(128)
    struct.pack_into("<6f", data, 0, 0.1, 1.0, 0.0, 1.0, 1.5, 1.0)
    struct.pack_into("<i", data, 24, 1)
    for offset in range(28, 60, 4):
        struct.pack_into("<f", data, offset, 1.0)  # saturation nodes
    for offset in range(60, 92, 4):
        struct.pack_into("<f", data, offset, 0.0)  # hue nodes
    for offset in range(92, 124, 4):
        struct.pack_into("<f", data, offset, 1.0)  # brightness nodes
    return bytes(data)


def _ashift_v5() -> bytes:
    data = bytearray(892)
    struct.pack_into("<8f", data, 0, 0.0, 0.0, 0.0, 0.0, 28.0, 1.0, 100.0, 1.0)
    struct.pack_into("<2i", data, 32, 0, 0)  # generic lens, crop off
    struct.pack_into("<4f", data, 40, 0.0, 1.0, 0.0, 1.0)
    # 200 floats of line geometry, count=0, and the final 8-float quad.
    return bytes(data)


_DENOISEPROFILE_V12 = _denoiseprofile_v12()
_LENS_V10 = _lens_v10()
_COLOREQUAL_V4 = _colorequal_v4()
_ASHIFT_V5 = _ashift_v5()

# darktable's neutral blendop state.  It is the same compressed blob emitted
# by 5.4.1 for a newly-created non-blended module.
NEUTRAL_BLEND_PARAMS = "gz12eJxjYGBgkGAAgRNODESDBnsIHll8ANNSGQM="


def _specs() -> dict[str, ModuleSpec]:
    # (byte offset, struct kind, minimum, maximum).  Struct kinds are native
    # little-endian darktable values; all supported fields are 32-bit.
    denoise_fields: dict[str, tuple[int, str, float | int | None, float | int | None]] = {
        "radius": (0, "f", 0.0, 12.0),
        "nbhood": (4, "f", 1.0, 30.0),
        "strength": (8, "f", 0.001, 1000.0),
        "shadows": (12, "f", 0.0, 1.8),
        "bias": (16, "f", -1000.0, 100.0),
        "scattering": (20, "f", 0.0, 20.0),
        "central_pixel_weight": (24, "f", 0.0, 10.0),
        "overshooting": (28, "f", 0.001, 1000.0),
        "a_0": (32, "f", -1000.0, 1000.0),
        "a_1": (36, "f", -1000.0, 1000.0),
        "a_2": (40, "f", -1000.0, 1000.0),
        "b_0": (44, "f", -1000.0, 1000.0),
        "b_1": (48, "f", -1000.0, 1000.0),
        "b_2": (52, "f", -1000.0, 1000.0),
        "mode": (56, "i", 0, 4),
        "wb_adaptive_anscombe": (396, "i", 0, 1),
        "fix_anscombe_and_nlmeans_norm": (400, "i", 0, 1),
        "use_new_vst": (404, "i", 0, 1),
        "wavelet_color_mode": (408, "i", 0, 1),
        "compensate_hilite_pres": (412, "i", 0, 1),
    }
    for channel in range(6):
        for band in range(7):
            index = channel * 7 + band
            denoise_fields[f"x_{channel}_{band}"] = (60 + index * 4, "f", 0.0, 1.0)
            denoise_fields[f"y_{channel}_{band}"] = (228 + index * 4, "f", 0.0, 1.0)

    colorequal_fields: dict[str, tuple[int, str, float | int | None, float | int | None]] = {
        "threshold": (0, "f", 0.0, 0.3),
        "smoothing_hue": (4, "f", 0.05, 2.0),
        "contrast": (8, "f", -1.0, 1.0),
        "white_level": (12, "f", -2.0, 16.0),
        "chroma_size": (16, "f", 1.0, 10.0),
        "param_size": (20, "f", 1.0, 128.0),
        "use_filter": (24, "i", 0, 1),
        "hue_shift": (124, "f", -23.0, 23.0),
    }
    for prefix, start, minimum, maximum in (
        ("sat", 28, 0.0, 2.0),
        ("hue", 60, -180.0, 180.0),
        ("bright", 92, 0.0, 2.0),
    ):
        for index, name in enumerate(("red", "orange", "yellow", "green", "cyan", "blue", "lavender", "magenta")):
            colorequal_fields[f"{prefix}_{name}"] = (start + index * 4, "f", minimum, maximum)

    return {
        "exposure": ModuleSpec(
            "exposure",
            7,
            _EXPOSURE_V7,
            {
                "mode": (0, "i", 0, 1),
                "black": (4, "f", -1.0, 1.0),
                "exposure": (8, "f", -18.0, 18.0),
                "deflicker_percentile": (12, "f", 0.0, 100.0),
                "deflicker_target_level": (16, "f", -18.0, 18.0),
                "compensate_exposure_bias": (20, "i", 0, 1),
                "compensate_hilite_pres": (24, "i", 0, 1),
            },
            integer_fields=frozenset(
                {"mode", "compensate_exposure_bias", "compensate_hilite_pres"}
            ),
            one_instance=False,
        ),
        "temperature": ModuleSpec(
            "temperature",
            4,
            _TEMPERATURE_V4,
            {
                "red": (0, "f", 0.0, 8.0),
                "green": (4, "f", 0.0, 8.0),
                "blue": (8, "f", 0.0, 8.0),
                # darktable uses -2 as the "unknown/auto" sentinel in the
                # fourth coefficient even though the GUI sliders are positive.
                "various": (12, "f", -2.0, 8.0),
                "preset": (16, "i", -1, 4),
            },
            integer_fields=frozenset({"preset"}),
            one_instance=True,
        ),
        "sigmoid": ModuleSpec(
            "sigmoid",
            3,
            _SIGMOID_V3,
            {
                "middle_grey_contrast": (0, "f", 0.1, 10.0),
                "contrast_skewness": (4, "f", -1.0, 1.0),
                "display_white_target": (8, "f", 20.0, 1600.0),
                "display_black_target": (12, "f", 0.0, 15.0),
                "color_processing": (16, "i", 0, 1),
                "hue_preservation": (20, "f", 0.0, 100.0),
                "red_inset": (24, "f", 0.0, 0.99),
                "red_rotation": (28, "f", -0.4, 0.4),
                "green_inset": (32, "f", 0.0, 0.99),
                "green_rotation": (36, "f", -0.4, 0.4),
                "blue_inset": (40, "f", 0.0, 0.99),
                "blue_rotation": (44, "f", -0.4, 0.4),
                "purity": (48, "f", 0.0, 1.0),
                "base_primaries": (52, "i", 0, 4),
            },
            integer_fields=frozenset({"color_processing", "base_primaries"}),
            one_instance=True,
        ),
        "filmicrgb": ModuleSpec(
            "filmicrgb",
            6,
            _FILMIC_RGB_V6,
            {
                "grey_point_source": (0, "f", 0.0, 100.0),
                "black_point_source": (4, "f", -16.0, -0.1),
                "white_point_source": (8, "f", 0.1, 16.0),
                "reconstruct_threshold": (12, "f", -6.0, 6.0),
                "reconstruct_feather": (16, "f", 0.25, 6.0),
                "reconstruct_bloom_vs_details": (20, "f", -100.0, 100.0),
                "reconstruct_grey_vs_color": (24, "f", -100.0, 100.0),
                "reconstruct_structure_vs_texture": (28, "f", -100.0, 100.0),
                "security_factor": (32, "f", -50.0, 200.0),
                "grey_point_target": (36, "f", 1.0, 50.0),
                "black_point_target": (40, "f", 0.0, 20.0),
                "white_point_target": (44, "f", 0.0, 1600.0),
                "output_power": (48, "f", 1.0, 10.0),
                "latitude": (52, "f", 0.01, 99.0),
                "contrast": (56, "f", 0.0, 5.0),
                "saturation": (60, "f", -200.0, 200.0),
                "balance": (64, "f", -50.0, 50.0),
                "noise_level": (68, "f", 0.0, 6.0),
                "preserve_color": (72, "i", 0, 5),
                "version": (76, "i", 0, 4),
                "auto_hardness": (80, "i", 0, 1),
                "custom_grey": (84, "i", 0, 1),
                "high_quality_reconstruction": (88, "i", 0, 10),
                "noise_distribution": (92, "i", 0, 2),
                "shadows": (96, "i", 0, 2),
                "highlights": (100, "i", 0, 2),
                "compensate_icc_black": (104, "i", 0, 1),
                "spline_version": (108, "i", 0, 2),
                "enable_highlight_reconstruction": (112, "i", 0, 1),
            },
            integer_fields=frozenset(
                {
                    "preserve_color",
                    "version",
                    "auto_hardness",
                    "custom_grey",
                    "high_quality_reconstruction",
                    "noise_distribution",
                    "shadows",
                    "highlights",
                    "compensate_icc_black",
                    "spline_version",
                    "enable_highlight_reconstruction",
                }
            ),
            one_instance=True,
        ),
        "colorbalancergb": ModuleSpec(
            "colorbalancergb",
            5,
            _COLORBALANCE_RGB_V5,
            {
                "shadows_Y": (0, "f", -1.0, 1.0),
                "shadows_C": (4, "f", 0.0, 1.0),
                "shadows_H": (8, "f", 0.0, 360.0),
                "midtones_Y": (12, "f", -1.0, 1.0),
                "midtones_C": (16, "f", 0.0, 1.0),
                "midtones_H": (20, "f", 0.0, 360.0),
                "highlights_Y": (24, "f", -1.0, 1.0),
                "highlights_C": (28, "f", 0.0, 1.0),
                "highlights_H": (32, "f", 0.0, 360.0),
                "global_Y": (36, "f", -1.0, 1.0),
                "global_C": (40, "f", 0.0, 1.0),
                "global_H": (44, "f", 0.0, 360.0),
                "shadows_weight": (48, "f", 0.0, 1.0),
                "white_fulcrum": (52, "f", 0.0, 1.0),
                "highlights_weight": (56, "f", 0.0, 1.0),
                "chroma_shadows": (60, "f", -1.0, 1.0),
                "chroma_highlights": (64, "f", -1.0, 1.0),
                "chroma_global": (68, "f", -1.0, 1.0),
                "chroma_midtones": (72, "f", -1.0, 1.0),
                "saturation_global": (76, "f", -1.0, 1.0),
                "saturation_highlights": (80, "f", -1.0, 1.0),
                "saturation_midtones": (84, "f", -1.0, 1.0),
                "saturation_shadows": (88, "f", -1.0, 1.0),
                "hue_angle": (92, "f", -360.0, 360.0),
                "brilliance_global": (96, "f", -1.0, 1.0),
                "brilliance_highlights": (100, "f", -1.0, 1.0),
                "brilliance_midtones": (104, "f", -1.0, 1.0),
                "brilliance_shadows": (108, "f", -1.0, 1.0),
                "mask_grey_fulcrum": (112, "f", 0.0, 1.0),
                "vibrance": (116, "f", -1.0, 1.0),
                "grey_fulcrum": (120, "f", 0.0, 1.0),
                "contrast": (124, "f", -1.0, 1.0),
                "saturation_formula": (128, "i", 0, 1),
            },
            integer_fields=frozenset({"saturation_formula"}),
            one_instance=False,
        ),
        "crop": ModuleSpec(
            "crop",
            3,
            _CROP_V3,
            {
                "cx": (0, "f", 0.0, 1.0),
                "cy": (4, "f", 0.0, 1.0),
                "cw": (8, "f", 0.0, 1.0),
                "ch": (12, "f", 0.0, 1.0),
                "ratio_n": (16, "i", -1, 10000),
                "ratio_d": (20, "i", -1, 10000),
            },
            integer_fields=frozenset({"ratio_n", "ratio_d"}),
            one_instance=True,
        ),
        "highlights": ModuleSpec(
            "highlights",
            4,
            _HIGHLIGHTS_V4,
            {
                "mode": (0, "i", 0, 5),
                "blendL": (4, "f", 0.0, 1.0),
                "blendC": (8, "f", 0.0, 1.0),
                "strength": (12, "f", 0.0, 1.0),
                "clip": (16, "f", 0.0, 2.0),
                "noise_level": (20, "f", 0.0, 0.5),
                "iterations": (24, "i", 1, 256),
                "scales": (28, "i", 0, 11),
                "candidating": (32, "f", 0.0, 1.0),
                "combine": (36, "f", 0.0, 8.0),
                "recovery": (40, "i", 0, 6),
                "solid_color": (44, "f", 0.0, 1.0),
            },
            integer_fields=frozenset({"mode", "iterations", "scales", "recovery"}),
            one_instance=True,
        ),
        "demosaic": ModuleSpec(
            "demosaic",
            6,
            _DEMOSAIC_V6,
            {
                "green_eq": (0, "i", 0, 3),
                "median_thrs": (4, "f", 0.0, 1.0),
                "color_smoothing": (8, "i", 0, 5),
                "demosaicing_method": (12, "i", 0, 2053),
                "lmmse_refine": (16, "i", 0, 4),
                "dual_thrs": (20, "f", 0.0, 1.0),
                "cs_radius": (24, "f", 0.0, 1.5),
                "cs_thrs": (28, "f", 0.0, 1.0),
                "cs_boost": (32, "f", 0.0, 1.5),
                "cs_iter": (36, "i", 1, 25),
                "cs_center": (40, "f", 0.0, 1.0),
                "cs_enabled": (44, "i", 0, 1),
            },
            integer_fields=frozenset(
                {"green_eq", "color_smoothing", "demosaicing_method", "lmmse_refine", "cs_iter", "cs_enabled"}
            ),
            allowed_values={
                # The 5.4.1 enum combines the X-Trans and dual flags with the
                # base method; arbitrary integers in the old 0..2052 range
                # can otherwise reach an undefined algorithm branch.
                "demosaicing_method": frozenset(
                    {
                        0, 1, 2, 3, 4, 5, 6, 7,
                        1024, 1025, 1026, 1027, 1028, 1029,
                        2049, 2050, 2053,
                    }
                ),
            },
            one_instance=True,
        ),
        "denoiseprofile": ModuleSpec(
            "denoiseprofile",
            12,
            _DENOISEPROFILE_V12,
            denoise_fields,
            integer_fields=frozenset(
                {
                    "mode",
                    "wb_adaptive_anscombe",
                    "fix_anscombe_and_nlmeans_norm",
                    "use_new_vst",
                    "wavelet_color_mode",
                    "compensate_hilite_pres",
                }
            ),
        ),
        "lens": ModuleSpec(
            "lens",
            10,
            _LENS_V10,
            {
                "method": (0, "i", 0, 2),
                "modify_flags": (4, "i", 0, 7),
                "inverse": (8, "i", 0, 1),
                "scale": (12, "f", 0.1, 2.0),
                "crop": (16, "f", 0.0, 2.0),
                "focal": (20, "f", 0.0, 2000.0),
                "aperture": (24, "f", 0.0, 100.0),
                "distance": (28, "f", 0.0, 1000000.0),
                "target_geom": (32, "i", 0, 8),
                "tca_override": (292, "i", 0, 1),
                "tca_r": (296, "f", 0.99, 1.01),
                "tca_b": (300, "f", 0.99, 1.01),
                "cor_dist_ft": (304, "f", 0.0, 2.0),
                "cor_vig_ft": (308, "f", 0.0, 2.0),
                "cor_ca_r_ft": (312, "f", 0.0, 2.0),
                "cor_ca_b_ft": (316, "f", 0.0, 2.0),
                "scale_md_v1": (320, "f", 0.9, 1.1),
                "md_version": (324, "i", 0, 1),
                "scale_md": (328, "f", 0.1, 2.0),
                "has_been_set": (332, "i", 0, 1),
                "v_strength": (336, "f", 0.0, 1.0),
                "v_radius": (340, "f", 0.0, 1.0),
                "v_steepness": (344, "f", 0.0, 1.0),
            },
            integer_fields=frozenset({"method", "modify_flags", "inverse", "target_geom", "tca_override", "md_version", "has_been_set"}),
            string_fields={"camera": (36, 128), "lens": (164, 128)},
        ),
        "sharpen": ModuleSpec(
            "sharpen",
            1,
            _SHARPEN_V1,
            {
                "radius": (0, "f", 0.0, 99.0),
                "amount": (4, "f", 0.0, 2.0),
                "threshold": (8, "f", 0.0, 100.0),
            },
        ),
        "diffuse": ModuleSpec(
            "diffuse",
            2,
            _DIFFUSE_V2,
            {
                "iterations": (0, "i", 0, 500),
                "sharpness": (4, "f", -1.0, 1.0),
                "radius": (8, "i", 0, 2048),
                "regularization": (12, "f", 0.0, 4.0),
                "variance_threshold": (16, "f", -2.0, 2.0),
                "anisotropy_first": (20, "f", -10.0, 10.0),
                "anisotropy_second": (24, "f", -10.0, 10.0),
                "anisotropy_third": (28, "f", -10.0, 10.0),
                "anisotropy_fourth": (32, "f", -10.0, 10.0),
                "threshold": (36, "f", 0.0, 8.0),
                "first": (40, "f", -1.0, 1.0),
                "second": (44, "f", -1.0, 1.0),
                "third": (48, "f", -1.0, 1.0),
                "fourth": (52, "f", -1.0, 1.0),
                "radius_center": (56, "i", 0, 1024),
            },
            integer_fields=frozenset({"iterations", "radius", "radius_center"}),
        ),
        "toneequal": ModuleSpec(
            "toneequal",
            2,
            _TONEEQUAL_V2,
            {
                "noise": (0, "f", -2.0, 2.0),
                "ultra_deep_blacks": (4, "f", -2.0, 2.0),
                "deep_blacks": (8, "f", -2.0, 2.0),
                "blacks": (12, "f", -2.0, 2.0),
                "shadows": (16, "f", -2.0, 2.0),
                "midtones": (20, "f", -2.0, 2.0),
                "highlights": (24, "f", -2.0, 2.0),
                "whites": (28, "f", -2.0, 2.0),
                "speculars": (32, "f", -2.0, 2.0),
                "blending": (36, "f", 0.01, 100.0),
                "smoothing": (40, "f", 0.01, 100.0),
                "feathering": (44, "f", 0.01, 10000.0),
                "quantization": (48, "f", 0.0, 2.0),
                "contrast_boost": (52, "f", -16.0, 16.0),
                "exposure_boost": (56, "f", -16.0, 16.0),
                "details": (60, "i", 0, 4),
                "method": (64, "i", 0, 2),
                "iterations": (68, "i", 1, 20),
            },
            integer_fields=frozenset({"details", "method", "iterations"}),
        ),
        "colorequal": ModuleSpec(
            "colorequal",
            4,
            _COLOREQUAL_V4,
            colorequal_fields,
            integer_fields=frozenset({"use_filter"}),
        ),
        "ashift": ModuleSpec(
            "ashift",
            5,
            _ASHIFT_V5,
            {
                "rotation": (0, "f", -180.0, 180.0),
                "lensshift_v": (4, "f", -2.0, 2.0),
                "lensshift_h": (8, "f", -2.0, 2.0),
                "shear": (12, "f", -0.5, 0.5),
                "f_length": (16, "f", 1.0, 2000.0),
                "crop_factor": (20, "f", 0.5, 10.0),
                "orthocorr": (24, "f", 0.0, 100.0),
                "aspect": (28, "f", 0.5, 2.0),
                "mode": (32, "i", 0, 1),
                "cropmode": (36, "i", 0, 2),
                "cl": (40, "f", 0.0, 1.0),
                "cr": (44, "f", 0.0, 1.0),
                "ct": (48, "f", 0.0, 1.0),
                "cb": (52, "f", 0.0, 1.0),
            },
            integer_fields=frozenset({"mode", "cropmode"}),
            one_instance=True,
        ),
    }


MODULE_SPECS = _specs()


def supported_operations() -> tuple[str, ...]:
    """Return operations whose C struct layouts are codec-verified."""

    return tuple(MODULE_SPECS)


def _decode_params(value: str) -> bytes:
    """Decode darktable's raw-hex or ``gz`` XMP parameter representation."""

    if not isinstance(value, str) or not value:
        raise DarktableCodecError("darktable module params must be a non-empty string")
    if value.startswith("gz"):
        # 5.4.1 prefixes the zlib payload with a four-character codec marker
        # (usually gz09).  We key off the zlib base64 signature rather than
        # accepting arbitrary XML prefixes.
        marker = value.find("eJ")
        if marker < 0:
            raise DarktableCodecError("darktable compressed params have no zlib payload")
        try:
            return __import__("zlib").decompress(base64.b64decode(value[marker:]))
        except (ValueError, binascii.Error, __import__("zlib").error) as error:
            raise DarktableCodecError("darktable compressed params are invalid") from error
    try:
        return bytes.fromhex(value)
    except ValueError as error:
        raise DarktableCodecError("darktable params must be raw hex or a verified gz payload") from error


def _encode_params(value: bytes) -> str:
    # Raw hex is the least ambiguous format and is accepted by darktable's
    # XMP reader.  It also makes the generated plan deterministic and reviewable.
    return value.hex()


def _set_field(data: bytearray, spec: ModuleSpec, name: str, value: Any) -> None:
    if name not in spec.fields:
        raise DarktableCodecError(
            f"{spec.operation} does not expose a codec-verified field named {name!r}"
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DarktableCodecError(f"{spec.operation}.{name} must be a finite number")
    offset, kind, minimum, maximum = spec.fields[name]
    if name in spec.integer_fields and (not isinstance(value, int) or isinstance(value, bool)):
        raise DarktableCodecError(f"{spec.operation}.{name} must be an integer")
    number: float | int = int(value) if name in spec.integer_fields else float(value)
    if name not in spec.integer_fields:
        import math

        if not math.isfinite(float(number)):
            raise DarktableCodecError(f"{spec.operation}.{name} must be finite")
    if minimum is not None and number < minimum:
        raise DarktableCodecError(f"{spec.operation}.{name} is below the verified range")
    if maximum is not None and number > maximum:
        raise DarktableCodecError(f"{spec.operation}.{name} is above the verified range")
    if spec.allowed_values and name in spec.allowed_values and int(number) not in spec.allowed_values[name]:
        allowed = ", ".join(str(item) for item in sorted(spec.allowed_values[name]))
        raise DarktableCodecError(
            f"{spec.operation}.{name} must be one of the verified values: {allowed}"
        )
    struct.pack_into("<" + kind, data, offset, number)


def _set_string_field(data: bytearray, spec: ModuleSpec, name: str, value: Any) -> None:
    if not spec.string_fields or name not in spec.string_fields:
        raise DarktableCodecError(
            f"{spec.operation} does not expose a codec-verified field named {name!r}"
        )
    if not isinstance(value, str) or "\x00" in value:
        raise DarktableCodecError(f"{spec.operation}.{name} must be a NUL-free string")
    offset, max_bytes = spec.string_fields[name]
    encoded = value.encode("utf-8")
    if len(encoded) >= max_bytes:
        raise DarktableCodecError(
            f"{spec.operation}.{name} must be fewer than {max_bytes} UTF-8 bytes"
        )
    data[offset : offset + max_bytes] = b"\x00" * max_bytes
    data[offset : offset + len(encoded)] = encoded


def encode_module(module: Mapping[str, Any]) -> dict[str, Any]:
    """Encode one validated module request to an XMP history payload."""

    if not isinstance(module, Mapping):
        raise DarktableCodecError("darktable module request must be an object")
    unknown = set(module) - {"operation", "params", "enabled", "multi_name", "multi_priority", "replace"}
    if unknown:
        raise DarktableCodecError(
            "darktable module request contains unknown fields: " + ", ".join(sorted(unknown))
        )
    operation = module.get("operation")
    if operation not in MODULE_SPECS:
        raise DarktableCodecError(
            f"darktable operation {operation!r} is not verified for {DARKTABLE_VERSION}; "
            f"supported: {', '.join(sorted(MODULE_SPECS))}"
        )
    spec = MODULE_SPECS[operation]
    params = module.get("params", {})
    if not isinstance(params, Mapping):
        raise DarktableCodecError(f"darktable.{operation}.params must be an object")
    known_params = set(spec.fields) | set(spec.string_fields or {})
    unknown_params = set(params) - known_params
    if unknown_params:
        raise DarktableCodecError(
            f"darktable.{operation}.params contains unverified fields: "
            + ", ".join(sorted(unknown_params))
        )
    data = bytearray(spec.template)
    for name, value in params.items():
        if spec.string_fields and name in spec.string_fields:
            _set_string_field(data, spec, name, value)
        else:
            _set_field(data, spec, name, value)
    enabled = module.get("enabled", True)
    if not isinstance(enabled, bool):
        raise DarktableCodecError(f"darktable.{operation}.enabled must be boolean")
    multi_name = module.get("multi_name", "")
    if not isinstance(multi_name, str) or len(multi_name) > 256:
        raise DarktableCodecError(f"darktable.{operation}.multi_name must be <=256 characters")
    multi_priority = module.get("multi_priority", 0)
    if isinstance(multi_priority, bool) or not isinstance(multi_priority, int):
        raise DarktableCodecError(f"darktable.{operation}.multi_priority must be an integer")
    if not MULTI_PRIORITY_MIN <= multi_priority <= MULTI_PRIORITY_MAX:
        raise DarktableCodecError(
            f"darktable.{operation}.multi_priority must be in the safe range "
            f"{MULTI_PRIORITY_MIN}..{MULTI_PRIORITY_MAX}"
        )
    replace = module.get("replace", spec.one_instance)
    if not isinstance(replace, bool):
        raise DarktableCodecError(f"darktable.{operation}.replace must be boolean")
    return {
        "operation": operation,
        "enabled": enabled,
        "modversion": spec.modversion,
        "params": _encode_params(bytes(data)),
        "multi_name": multi_name,
        "multi_priority": multi_priority,
        "blendop_version": 13,
        "blendop_params": NEUTRAL_BLEND_PARAMS,
        "replace": replace,
    }


def _new_xmp() -> ET.Element:
    root = ET.Element("{adobe:ns:meta/}xmpmeta")
    rdf = ET.SubElement(root, f"{{{RDF_NS}}}RDF")
    desc = ET.SubElement(
        rdf,
        f"{{{RDF_NS}}}Description",
        {
            f"{{{XMP_NS}}}Rating": "0",
            f"{{{DT_NS}}}xmp_version": DARKTABLE_XMP_VERSION,
            f"{{{DT_NS}}}raw_params": "0",
            f"{{{DT_NS}}}auto_presets_applied": "0",
            f"{{{DT_NS}}}history_end": "0",
            f"{{{DT_NS}}}iop_order_version": "5",
        },
    )
    for name in ("masks_history", "history"):
        property_node = ET.SubElement(desc, f"{{{DT_NS}}}{name}")
        ET.SubElement(property_node, f"{{{RDF_NS}}}Seq")
    return root


def minimal_xmp() -> str:
    """Return a current 5.4.1 empty-history XMP starting state.

    The app bundle's ``profiling-shot.xmp`` is a user-facing sample from an
    older XMP schema and contains module payloads that are not safe generic
    defaults.  Dynamic plans and live verification use this codec-owned
    version-5 state instead, then append only verified module structs.
    """

    return ET.tostring(_new_xmp(), encoding="unicode", short_empty_elements=True) + "\n"


def _description(root: ET.Element) -> ET.Element:
    desc = root.find(f".//{{{RDF_NS}}}Description")
    if desc is None:
        raise DarktableCodecError("darktable XMP has no RDF Description")
    return desc


def _history_seq(root: ET.Element) -> ET.Element:
    history = root.find(f".//{{{DT_NS}}}history/{{{RDF_NS}}}Seq")
    if history is None:
        desc = _description(root)
        history_property = ET.SubElement(desc, f"{{{DT_NS}}}history")
        history = ET.SubElement(history_property, f"{{{RDF_NS}}}Seq")
    return history


def _parse_xmp(text: str) -> ET.Element:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise DarktableCodecError("base darktable XMP is not valid XML") from error
    # darktable uses the x:xmpmeta root.  Do not accept arbitrary RDF because
    # it may be a Lightroom sidecar with no darktable history semantics.
    if root.tag != "{adobe:ns:meta/}xmpmeta":
        raise DarktableCodecError("base profile is not a darktable xmpmeta document")
    desc = _description(root)
    if desc.get(_module_attr("xmp_version")) != DARKTABLE_XMP_VERSION:
        raise DarktableCodecError(
            f"darktable XMP xmp_version must be {DARKTABLE_XMP_VERSION} for {DARKTABLE_VERSION}"
        )
    _history_seq(root)
    return root


def validate_xmp(text: str) -> None:
    """Validate that *text* is a darktable XMP document accepted by the codec."""

    _parse_xmp(text)


def _module_attr(name: str) -> str:
    return f"{{{DT_NS}}}{name}"


def _remove_existing(history: ET.Element, operation: str) -> None:
    for child in list(history):
        if child.get(_module_attr("operation")) == operation:
            history.remove(child)


def _append_history(history: ET.Element, encoded: Mapping[str, Any]) -> None:
    ET.SubElement(
        history,
        f"{{{RDF_NS}}}li",
        {
            _module_attr("operation"): str(encoded["operation"]),
            _module_attr("enabled"): "1" if encoded["enabled"] else "0",
            _module_attr("modversion"): str(encoded["modversion"]),
            _module_attr("params"): str(encoded["params"]),
            _module_attr("multi_name"): str(encoded["multi_name"]),
            _module_attr("multi_priority"): str(encoded["multi_priority"]),
            _module_attr("blendop_version"): str(encoded["blendop_version"]),
            _module_attr("blendop_params"): str(encoded["blendop_params"]),
        },
    )


def compile_xmp(
    base_xmp: str | None,
    modules: list[Mapping[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Compile verified module requests into a complete darktable XMP.

    ``base_xmp`` is preserved history unless a module's ``replace`` flag is
    true.  Each returned module record is canonical and can be included in an
    execution plan for audit/replay.
    """

    if not isinstance(modules, list) or not modules:
        raise DarktableCodecError("at least one darktable module is required")
    root = _new_xmp() if base_xmp is None else _parse_xmp(base_xmp)
    history = _history_seq(root)
    encoded_modules: list[dict[str, Any]] = []
    for module in modules:
        encoded = encode_module(module)
        if encoded["replace"]:
            _remove_existing(history, str(encoded["operation"]))
        _append_history(history, encoded)
        encoded_modules.append(encoded)
    _description(root).set(_module_attr("history_end"), str(len(history)))
    payload = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return payload + "\n", encoded_modules


def modules_from_global_adjustments(adjustments: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Map the vendor-neutral subset to exact darktable module fields.

    The mapping is intentionally small and explicit.  Callers should send
    engine-specific modules for controls whose semantics are not equivalent;
    unsupported global fields fail closed instead of being silently ignored.
    """

    if not isinstance(adjustments, Mapping):
        raise DarktableCodecError("global adjustments must be an object")
    unknown = set(adjustments) - {"exposure_ev", "black_point", "contrast", "saturation"}
    if unknown:
        raise DarktableCodecError(
            "darktable global mapping is not verified for: " + ", ".join(sorted(unknown))
        )
    modules: list[dict[str, Any]] = []
    exposure: dict[str, Any] = {}
    if "exposure_ev" in adjustments:
        exposure["exposure"] = adjustments["exposure_ev"]
    if "black_point" in adjustments:
        exposure["black"] = adjustments["black_point"]
    if exposure:
        modules.append({"operation": "exposure", "params": exposure, "replace": True})
    color: dict[str, Any] = {}
    if "contrast" in adjustments:
        # color balance RGB's contrast is a normalized scene-referred control.
        color["contrast"] = float(adjustments["contrast"]) / 100.0
    if "saturation" in adjustments:
        color["saturation_global"] = float(adjustments["saturation"]) / 100.0
    if color:
        modules.append(
            {"operation": "colorbalancergb", "params": color, "replace": True}
        )
    if not modules:
        raise DarktableCodecError("no verified darktable global adjustments were requested")
    return modules


def module_summary(modules: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return a safe, non-payload summary for capability/report documents."""

    return [
        {
            "operation": item.get("operation"),
            "fields": (
                sorted(item.get("params", {}).keys())
                if isinstance(item.get("params"), Mapping)
                else []
            ),
            "enabled": item.get("enabled", True),
        }
        for item in modules
    ]
