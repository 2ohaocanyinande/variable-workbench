"""Compare actual code tokens while ignoring presentation line numbers/spacing."""
import re

TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?|>>=|<<=|->|\+\+|--|&&|\|\||==|!=|<=|>=|<<|>>|\+=|-=|\*=|/=|%=|&=|\|=|\^=|::|[^\s]')


def tokens(text):
    text = re.sub(r'(?m)^[ \t]*\d+:[ \t]?', '', text)
    return TOKEN.findall(text)


def quote_exists(quote, code):
    if not isinstance(quote, str) or len(quote.strip()) < 4: return False
    needle, haystack = tokens(quote), tokens(code)
    if not needle: return False
    return any(haystack[i:i+len(needle)] == needle for i in range(len(haystack)-len(needle)+1))


def quote_source_line(quote, numbered_code):
    """Locate a verified quote in the local, original numbered snippet."""
    needle = tokens(quote)
    located = []
    for line in numbered_code.splitlines():
        match = re.match(r'^\s*(\d+):[ \t]?(.*)$', line)
        if match: located.extend((token, int(match[1])) for token in tokens(match[2]))
    haystack = [token for token, _ in located]
    for index in range(len(haystack)-len(needle)+1):
        if needle and haystack[index:index+len(needle)] == needle: return located[index][1]
    return None
