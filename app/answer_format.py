"""Answer formatting helpers that do not depend on the retrieval stack."""


def clip(text: str, limit: int = 400) -> str:
    """Cut on a word boundary so a figure is never split ("16,292" must not become "16,29")."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut.rsplit(None, 1)[0] if text[limit].strip() else cut
