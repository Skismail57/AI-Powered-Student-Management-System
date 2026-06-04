import html.parser

class TagChecker(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in ['br', 'hr', 'img', 'input', 'link', 'meta', 'base', 'col', 'embed', 'source', 'track', 'wbr']:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag not in ['br', 'hr', 'img', 'input', 'link', 'meta', 'base', 'col', 'embed', 'source', 'track', 'wbr']:
            if not self.stack:
                self.errors.append(f"Unexpected closing tag </{tag}> at line {self.getpos()[0]}")
            else:
                last_tag, pos = self.stack.pop()
                if last_tag != tag:
                    self.errors.append(f"Mismatched tag: opened <{last_tag}> at line {pos[0]}, but closed with </{tag}> at line {self.getpos()[0]}")

    def check_file(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.feed(content)
        if self.stack:
            for tag, pos in self.stack:
                self.errors.append(f"Unclosed tag <{tag}> at line {pos[0]}")
        return self.errors

checker = TagChecker()
errors = checker.check_file('frontend/admin.html')
if errors:
    for e in errors:
        print(e)
else:
    print("No tag mismatches found.")
