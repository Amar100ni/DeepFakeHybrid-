def fuse_scores(vscore, ascore, motion_flag):
    """
    Weighted fusion of video + audio deepfake scores.
    Weights: video=0.55, audio=0.45 (normalized to 1.0).
    motion_flag=False adds a 0.10 penalty (indicates lip-sync desync).
    Result is always clamped to [0.0, 1.0].
    """
    base = (0.55 * vscore) + (0.45 * ascore)
    motion_penalty = 0.10 if not motion_flag else 0.0
    return min(max(base + motion_penalty, 0.0), 1.0)
