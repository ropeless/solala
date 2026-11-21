import re


def compile_register_filter(pattern: str) -> re.Pattern[str]:
    """
    Compile a register-name filter for use with Pattern.match.

    Matches anywhere in the name unless anchored at the beginning.
    """
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == '\\':
            index += 1
            if index == len(pattern) or pattern[index] not in ('^', '$', '*', '?', '\\'):
                raise ValueError('invalid pattern escape')
            parts.append(re.escape(pattern[index]))
        elif char == '^':
            if index != 0:
                raise ValueError('^ must be at the start')
        elif char == '$':
            if index != len(pattern) - 1:
                raise ValueError('$ must be at the end')
            parts.append('$')
        elif char == '*':
            parts.append('.*')
        elif char == '?':
            parts.append('.')
        else:
            parts.append(re.escape(char))
        index += 1
    return re.compile(('' if pattern.startswith('^') else '.*') + ''.join(parts))
