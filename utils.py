"""Мелкие форматтеры, общие для синка и генерации."""


def human_readable_size(size_bytes) -> str:
    """Размер в байтах -> '1.23 MB' (без JS на странице)."""
    value = float(size_bytes or 0)
    if value <= 0:
        return "0 B"
    names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while value >= 1024 and i < len(names) - 1:
        value /= 1024
        i += 1
    return f"{value:.2f} {names[i]}"
