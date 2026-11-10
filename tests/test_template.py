import unittest
from unittest import mock

import helpers  # noqa: F401  (adds src/ to sys.path)

from pahest import template


def render(text: str, values: dict, files: dict = None) -> str:
    """Render template text (and partials by name) without touching the template files."""
    files = dict(files or {}, **{"t": text})
    template._tree.cache_clear()
    with mock.patch.object(template, "source", side_effect=lambda name: files[name]):
        try:
            return template.render("t", values)
        finally:
            template._tree.cache_clear()


class TemplateTest(unittest.TestCase):
    def test_values_are_escaped_unless_in_three_braces(self):
        self.assertEqual(render("<b>{{x}}</b> {{{x}}} {{missing}}{{n}}", {"x": "<a & b>", "n": 0}),
                         "<b>&lt;a &amp; b&gt;</b> <a & b> 0")

    def test_sections_lists_and_missing_values(self):
        text = "{{#rows}}{{name}}={{value}}{{^last}}, {{/last}}{{/rows}}{{^rows}}none{{/rows}} {{#on}}yes {{title}}{{/on}}"
        rows = [{"name": "a", "value": 1}, {"name": "b", "value": 2, "last": True}]
        self.assertEqual(render(text, {"rows": rows, "on": True, "title": "T"}), "a=1, b=2 yes T")
        self.assertEqual(render(text, {"rows": [], "on": ""}), "none ")
        self.assertEqual(render("{{#tags}}[{{.}}]{{/tags}}", {"tags": ["x", "<y>"]}), "[x][&lt;y&gt;]")

    def test_an_inner_value_hides_an_outer_one_even_when_empty(self):
        text = "{{#items}}{{#note}}({{note}}){{/note}}{{/items}}"
        self.assertEqual(render(text, {"note": "outer", "items": [{"note": ""}, {"note": "in"}, {}]}), "(in)(outer)")

    def test_partials_comments_and_tags_alone_on_a_line(self):
        text = "<ul>\n{{! a list }}\n{{#items}}\n{{> row}}\n{{/items}}\n</ul>\n"
        self.assertEqual(render(text, {"items": [{"v": 1}, {"v": 2}]}, {"row": "<li>{{v}}</li>\n"}),
                         "<ul>\n<li>1</li>\n<li>2</li>\n</ul>\n")

    def test_a_section_left_open_is_an_error(self):
        with self.assertRaises(template.TemplateError):
            render("{{#a}}x", {})
        with self.assertRaises(template.TemplateError):
            render("{{#a}}x{{/b}}", {})

    def test_every_template_file_can_be_read(self):
        for path in template.FOLDER.iterdir():
            template._tree(path.name)                     # raises TemplateError on a broken file


if __name__ == "__main__":
    unittest.main()
