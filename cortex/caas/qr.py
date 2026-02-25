"""
Minimal QR Code Model 2 encoder — pure Python, zero dependencies.

Supports byte mode, EC level M, versions 1-6 (~150 chars max).
Outputs SVG string with <rect> elements for dark modules.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# GF(256) arithmetic for Reed-Solomon
# ---------------------------------------------------------------------------

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256

def _init_gf() -> None:
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x >= 256:
            x ^= 0x11D  # primitive polynomial
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]

_init_gf()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator(nsym: int) -> list[int]:
    """Build RS generator polynomial of degree nsym."""
    g = [1]
    for i in range(nsym):
        ng = [0] * (len(g) + 1)
        for j in range(len(g)):
            ng[j] ^= g[j]
            ng[j + 1] ^= _gf_mul(g[j], _GF_EXP[i])
        g = ng
    return g


def _rs_encode(data: list[int], nsym: int) -> list[int]:
    """Compute RS error correction codewords."""
    gen = _rs_generator(nsym)
    msg = data + [0] * nsym
    for i in range(len(data)):
        coef = msg[i]
        if coef != 0:
            for j in range(len(gen)):
                msg[i + j] ^= _gf_mul(gen[j], coef)
    return msg[len(data):]


# ---------------------------------------------------------------------------
# QR Code version/EC tables (byte mode, EC level M)
# ---------------------------------------------------------------------------

# (total_codewords, ec_codewords_per_block, num_blocks, data_capacity_bytes)
_VERSION_TABLE = {
    1: (26, 10, 1, 14),
    2: (44, 16, 1, 26),
    3: (70, 26, 1, 42),
    4: (100, 18, 2, 62),
    5: (134, 24, 2, 84),
    6: (172, 16, 4, 106),
}

# Alignment pattern center positions per version
_ALIGNMENT = {
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
}

# Format info bits for EC level M (mask 0-7)
_FORMAT_BITS = [
    0x5412, 0x5125, 0x5E7C, 0x5B4B,
    0x45F9, 0x40CE, 0x4F97, 0x4AA0,
]


def _select_version(data_len: int) -> int:
    """Select smallest version that fits data_len bytes."""
    # Byte mode overhead: 4 (mode) + 8 or 16 (count) bits, plus terminator
    for v in range(1, 7):
        cap = _VERSION_TABLE[v][3]
        # Byte mode header: 4 bits mode + 8 bits count (v1-9)
        # Need: ceil((4 + 8 + data_len*8 + 4) / 8) data codewords
        total_bits = 4 + 8 + data_len * 8
        needed = (total_bits + 7) // 8
        if needed <= cap:
            return v
    raise ValueError(f"Data too long ({data_len} bytes) for QR versions 1-6")


# ---------------------------------------------------------------------------
# Module matrix construction
# ---------------------------------------------------------------------------

def _make_matrix(version: int) -> tuple[list[list[int]], list[list[bool]]]:
    """Create module matrix and reserved-area mask. 0=white, 1=dark."""
    size = 17 + version * 4
    matrix = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]
    return matrix, reserved


def _mark_reserved(reserved: list[list[bool]], r: int, c: int, size: int) -> None:
    if 0 <= r < size and 0 <= c < size:
        reserved[r][c] = True


def _place_finder(matrix: list[list[int]], reserved: list[list[bool]], row: int, col: int) -> None:
    """Place a 7x7 finder pattern centered at (row+3, col+3)."""
    size = len(matrix)
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if rr < 0 or rr >= size or cc < 0 or cc >= size:
                continue
            if 0 <= r <= 6 and 0 <= c <= 6:
                if (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)):
                    matrix[rr][cc] = 1
                else:
                    matrix[rr][cc] = 0
            else:
                matrix[rr][cc] = 0
            reserved[rr][cc] = True


def _place_alignment(matrix: list[list[int]], reserved: list[list[bool]], version: int) -> None:
    """Place alignment patterns for versions 2+."""
    if version < 2:
        return
    positions = _ALIGNMENT.get(version, [])
    centers = [(r, c) for r in positions for c in positions]
    # Exclude positions overlapping finder patterns
    size = len(matrix)
    for cr, cc in centers:
        # Skip if overlaps with finder + separator (top-left, top-right, bottom-left)
        if cr <= 8 and cc <= 8:
            continue
        if cr <= 8 and cc >= size - 8:
            continue
        if cr >= size - 8 and cc <= 8:
            continue
        for r in range(-2, 3):
            for c in range(-2, 3):
                rr, cc2 = cr + r, cc + c
                if abs(r) == 2 or abs(c) == 2 or (r == 0 and c == 0):
                    matrix[rr][cc2] = 1
                else:
                    matrix[rr][cc2] = 0
                reserved[rr][cc2] = True


def _place_timing(matrix: list[list[int]], reserved: list[list[bool]]) -> None:
    """Place timing patterns (row 6 and col 6)."""
    size = len(matrix)
    for i in range(8, size - 8):
        v = 1 if i % 2 == 0 else 0
        if not reserved[6][i]:
            matrix[6][i] = v
            reserved[6][i] = True
        if not reserved[i][6]:
            matrix[i][6] = v
            reserved[i][6] = True


def _reserve_format_areas(reserved: list[list[bool]], size: int) -> None:
    """Reserve format info areas around finders."""
    # Around top-left finder
    for i in range(9):
        _mark_reserved(reserved, 8, i, size)
        _mark_reserved(reserved, i, 8, size)
    # Around top-right finder
    for i in range(8):
        _mark_reserved(reserved, 8, size - 1 - i, size)
    # Around bottom-left finder
    for i in range(7):
        _mark_reserved(reserved, size - 1 - i, 8, size)
    # Dark module
    _mark_reserved(reserved, size - 8, 8, size)


def _encode_data(data: bytes, version: int) -> list[int]:
    """Encode data bytes into QR codewords with EC."""
    info = _VERSION_TABLE[version]
    total_cw, ec_per_block, num_blocks, data_cap = info

    # Build bit stream: mode (0100 = byte) + count (8 bits) + data + terminator
    bits: list[int] = []
    # Mode indicator: byte = 0100
    bits.extend([0, 1, 0, 0])
    # Character count (8 bits for versions 1-9)
    for i in range(7, -1, -1):
        bits.append((len(data) >> i) & 1)
    # Data bits
    for b in data:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    # Terminator (up to 4 zeros)
    total_data_bits = data_cap * 8
    term_len = min(4, total_data_bits - len(bits))
    bits.extend([0] * term_len)
    # Pad to byte boundary
    while len(bits) % 8 != 0:
        bits.append(0)
    # Pad codewords
    pad_patterns = [0xEC, 0x11]
    pi = 0
    while len(bits) < total_data_bits:
        for i in range(7, -1, -1):
            bits.append((pad_patterns[pi] >> i) & 1)
        pi = (pi + 1) % 2

    # Convert bits to codewords
    codewords = []
    for i in range(0, len(bits), 8):
        val = 0
        for j in range(8):
            if i + j < len(bits):
                val = (val << 1) | bits[i + j]
            else:
                val <<= 1
        codewords.append(val)

    # Split into blocks and compute EC for each
    data_cw_per_block = data_cap // num_blocks
    remainder = data_cap % num_blocks
    blocks_data: list[list[int]] = []
    blocks_ec: list[list[int]] = []
    offset = 0
    for b in range(num_blocks):
        count = data_cw_per_block + (1 if b >= num_blocks - remainder else 0)
        block = codewords[offset:offset + count]
        offset += count
        ec = _rs_encode(block, ec_per_block)
        blocks_data.append(block)
        blocks_ec.append(ec)

    # Interleave data codewords
    result: list[int] = []
    max_data = max(len(b) for b in blocks_data)
    for i in range(max_data):
        for b in blocks_data:
            if i < len(b):
                result.append(b[i])
    # Interleave EC codewords
    for i in range(ec_per_block):
        for b in blocks_ec:
            if i < len(b):
                result.append(b[i])

    return result


def _place_data(matrix: list[list[int]], reserved: list[list[bool]], codewords: list[int]) -> None:
    """Place data codewords into the matrix using the QR zigzag pattern."""
    size = len(matrix)
    # Convert to bit stream
    bits: list[int] = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    bit_idx = 0
    # Traverse columns right-to-left in pairs
    col = size - 1
    while col >= 0:
        if col == 6:  # skip timing column
            col -= 1
            continue
        # Two columns: col and col-1
        for going_up in (True, False):
            rows = range(size - 1, -1, -1) if going_up else range(size)
            for row in rows:
                for dc in (0, 1):
                    c = col - dc
                    if c < 0:
                        continue
                    if reserved[row][c]:
                        continue
                    if bit_idx < len(bits):
                        matrix[row][c] = bits[bit_idx]
                        bit_idx += 1
                    else:
                        matrix[row][c] = 0
            col -= 2
            break  # process one direction per pair, handled by outer while


def _place_data_v2(matrix: list[list[int]], reserved: list[list[bool]], codewords: list[int]) -> None:
    """Place data bits using proper QR zigzag traversal."""
    size = len(matrix)
    bits: list[int] = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    bit_idx = 0
    col = size - 1
    while col >= 0:
        if col == 6:
            col -= 1
        going_up = ((size - 1 - col) // 2) % 2 == 0
        rows = range(size - 1, -1, -1) if going_up else range(size)
        for row in rows:
            for dc in (0, 1):
                c = col - dc
                if c < 0:
                    continue
                if reserved[row][c]:
                    continue
                if bit_idx < len(bits):
                    matrix[row][c] = bits[bit_idx]
                    bit_idx += 1
                else:
                    matrix[row][c] = 0
        col -= 2


def _apply_mask(matrix: list[list[int]], reserved: list[list[bool]], mask_id: int) -> list[list[int]]:
    """Apply mask pattern to data modules (not reserved areas)."""
    size = len(matrix)
    result = [row[:] for row in matrix]
    for r in range(size):
        for c in range(size):
            if reserved[r][c]:
                continue
            invert = False
            if mask_id == 0:
                invert = (r + c) % 2 == 0
            elif mask_id == 1:
                invert = r % 2 == 0
            elif mask_id == 2:
                invert = c % 3 == 0
            elif mask_id == 3:
                invert = (r + c) % 3 == 0
            elif mask_id == 4:
                invert = (r // 2 + c // 3) % 2 == 0
            elif mask_id == 5:
                invert = (r * c) % 2 + (r * c) % 3 == 0
            elif mask_id == 6:
                invert = ((r * c) % 2 + (r * c) % 3) % 2 == 0
            elif mask_id == 7:
                invert = ((r + c) % 2 + (r * c) % 3) % 2 == 0
            if invert:
                result[r][c] ^= 1
    return result


def _place_format_info(matrix: list[list[int]], mask_id: int) -> None:
    """Write format info bits (EC level M + mask) into the matrix."""
    size = len(matrix)
    fmt = _FORMAT_BITS[mask_id]

    # Place around top-left finder
    bits_tl = []
    for i in range(14, -1, -1):
        bits_tl.append((fmt >> i) & 1)

    # Horizontal (row 8, columns 0-7 then skip timing at col 6)
    h_cols = [0, 1, 2, 3, 4, 5, 7, 8]
    for i, c in enumerate(h_cols):
        matrix[8][c] = bits_tl[i]

    # Vertical (column 8, rows 7 down to 0)
    v_rows = [7, 5, 4, 3, 2, 1, 0]
    for i, r in enumerate(v_rows):
        matrix[r][8] = bits_tl[8 + i]

    # Place around top-right and bottom-left
    # Top-right: row 8, columns (size-1) to (size-8)
    for i in range(7):
        matrix[8][size - 1 - i] = bits_tl[14 - i]

    # Bottom-left: column 8, rows (size-1) to (size-7)
    for i in range(7):
        matrix[size - 1 - i][8] = bits_tl[i]

    # Dark module
    matrix[size - 8][8] = 1


def _penalty_score(matrix: list[list[int]]) -> int:
    """Simplified penalty score for mask selection."""
    size = len(matrix)
    penalty = 0

    # Rule 1: runs of same color >= 5
    for r in range(size):
        run = 1
        for c in range(1, size):
            if matrix[r][c] == matrix[r][c - 1]:
                run += 1
            else:
                if run >= 5:
                    penalty += run - 2
                run = 1
        if run >= 5:
            penalty += run - 2

    for c in range(size):
        run = 1
        for r in range(1, size):
            if matrix[r][c] == matrix[r - 1][c]:
                run += 1
            else:
                if run >= 5:
                    penalty += run - 2
                run = 1
        if run >= 5:
            penalty += run - 2

    # Rule 2: 2x2 blocks
    for r in range(size - 1):
        for c in range(size - 1):
            v = matrix[r][c]
            if matrix[r][c + 1] == v and matrix[r + 1][c] == v and matrix[r + 1][c + 1] == v:
                penalty += 3

    return penalty


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_qr_svg(data: str, module_size: int = 4, border: int = 4) -> str:
    """Generate a QR Code SVG string for the given data.

    Args:
        data: Text to encode (max ~150 chars for versions 1-6).
        module_size: Pixel size of each module.
        border: Quiet zone modules around the code.

    Returns:
        SVG string with dark modules as rectangles.
    """
    data_bytes = data.encode("utf-8")
    version = _select_version(len(data_bytes))
    size = 17 + version * 4

    # Build base matrix
    matrix, reserved = _make_matrix(version)

    # Place function patterns
    _place_finder(matrix, reserved, 0, 0)
    _place_finder(matrix, reserved, 0, size - 7)
    _place_finder(matrix, reserved, size - 7, 0)
    _place_alignment(matrix, reserved, version)
    _place_timing(matrix, reserved)
    _reserve_format_areas(reserved, size)

    # Dark module
    matrix[size - 8][8] = 1

    # Encode and place data
    codewords = _encode_data(data_bytes, version)
    _place_data_v2(matrix, reserved, codewords)

    # Try all masks, pick lowest penalty
    best_mask = 0
    best_penalty = float("inf")
    best_matrix = matrix

    for mask_id in range(8):
        candidate = _apply_mask(matrix, reserved, mask_id)
        _place_format_info(candidate, mask_id)
        p = _penalty_score(candidate)
        if p < best_penalty:
            best_penalty = p
            best_mask = mask_id
            best_matrix = candidate

    # Build SVG
    total = size + border * 2
    svg_size = total * module_size
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {svg_size} {svg_size}" '
        f'width="{svg_size}" height="{svg_size}">',
        f'<rect width="{svg_size}" height="{svg_size}" fill="#fff"/>',
    ]

    for r in range(size):
        for c in range(size):
            if best_matrix[r][c] == 1:
                x = (c + border) * module_size
                y = (r + border) * module_size
                parts.append(
                    f'<rect x="{x}" y="{y}" '
                    f'width="{module_size}" height="{module_size}" fill="#000"/>'
                )

    parts.append("</svg>")
    return "\n".join(parts)
