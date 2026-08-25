# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

import frappe


def get_code128_svg(data, height=28, module_width=1.3):
	"""
	Generate a standalone, zero-dependency Code 128 (Set B) SVG string.
	Renders crisp vector barcodes in all browsers and PDF generators (WeasyPrint / Chrome).
	"""
	if not data:
		return ""

	data = str(data).strip()
	patterns = [
		"212222",
		"222122",
		"222221",
		"121223",
		"121322",
		"131222",
		"122213",
		"122312",
		"132212",
		"221213",
		"221312",
		"231212",
		"112232",
		"122132",
		"122231",
		"113222",
		"123122",
		"123221",
		"223211",
		"221132",
		"221231",
		"213212",
		"223112",
		"312131",
		"311222",
		"321122",
		"321221",
		"312212",
		"322112",
		"322211",
		"212123",
		"212321",
		"232121",
		"111323",
		"131123",
		"131321",
		"112313",
		"132113",
		"132311",
		"211313",
		"231113",
		"231311",
		"112133",
		"112331",
		"132131",
		"113123",
		"113321",
		"133121",
		"313121",
		"211331",
		"231131",
		"213113",
		"213311",
		"213131",
		"311123",
		"311321",
		"331121",
		"312113",
		"312311",
		"332111",
		"314111",
		"221411",
		"431111",
		"111224",
		"111422",
		"121124",
		"121421",
		"141122",
		"141221",
		"112214",
		"112412",
		"122114",
		"122411",
		"142112",
		"142211",
		"241211",
		"221114",
		"413111",
		"241112",
		"134111",
		"111242",
		"121142",
		"121241",
		"114212",
		"124112",
		"124211",
		"411212",
		"421112",
		"421211",
		"212141",
		"214121",
		"412121",
		"111143",
		"111341",
		"131141",
		"114113",
		"114311",
		"411113",
		"411311",
		"113141",
		"114131",
		"311141",
		"411131",
		"211412",
		"211214",
		"211232",
		"2331112",
	]
	start_code = 104
	stop_code = 106

	encoded = [start_code]
	for c in data:
		val = ord(c) - 32 if 32 <= ord(c) <= 126 else 0
		encoded.append(val)

	checksum = start_code + sum(i * v for i, v in enumerate(encoded[1:], 1))
	encoded.append(checksum % 103)
	encoded.append(stop_code)

	pattern_str = "".join(patterns[v] for v in encoded)
	total_modules = sum(int(d) for d in pattern_str)
	total_width = total_modules * module_width

	rects = []
	cur_x = 0.0
	is_bar = True
	for d in pattern_str:
		w = int(d) * module_width
		if is_bar:
			rects.append(f'<rect x="{cur_x:.1f}" y="0" width="{w:.1f}" height="{height}" fill="#000" />')
		cur_x += w
		is_bar = not is_bar

	svg = (
		f'<svg viewBox="0 0 {total_width:.1f} {height}" '
		f'style="max-width: 100%; height: {height}px; display: block;" '
		f'xmlns="http://www.w3.org/2000/svg">'
		f'{"".join(rects)}'
		f'</svg>'
	)
	return svg


def get_barcode(data):
	"""Wrapper for backwards compatibility."""
	return get_code128_svg(data)


def format_qty(qty):
	"""Format quantity to omit .0 for whole numbers while preserving non-zero fractions."""
	if qty is None or qty == "":
		return ""
	try:
		f = float(qty)
		if f.is_integer() or f % 1 == 0:
			return str(int(f))
		return str(f).rstrip("0").rstrip(".") if "." in str(f) else str(f)
	except (ValueError, TypeError):
		return str(qty)
