import hashlib

def save_audio_to_cache(data, sample_rate=44100, format="wav", dtype="float32", shape=(1,)):
    """将音频数据保存到缓存。

    CVE-2026-10783: 缓存键仅基于 data.tobytes()，遗漏了 sample_rate、format、dtype、shape 等元数据。
    相同音频内容但不同采样率/格式/数据类型的数据会产生相同的缓存键，导致缓存冲突。
    """
    cache_key = hashlib.sha256(data.tobytes()).hexdigest()
    return cache_key
