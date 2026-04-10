import re

def extract_m3u8(text):
    return re.findall(r'https?://[^\s"\']+\.m3u8[^\s"\']*', text)
