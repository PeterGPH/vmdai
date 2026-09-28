# P10-T03: the Markdown subset -> spans (Part B V4 "Markdown").  Pure Tcl.
package require tcltest 2
namespace import ::tcltest::*
source [file join $env(VMDAI_PLUGIN_DIR) markdown.tcl]

set FINAL "- **Protein** — NewCartoon\n- **ATP** — Licorice\n\nThe radius of gyration is **20.84 Å**. Run `measure rgyr`:\n\n```tcl\nset sel \[atomselect top protein\]\nmeasure rgyr \$sel\n```"

test md-subset-1 {items, bold, inline code and a fenced block} -body {
    ::vmdai::md::spans $FINAL
} -result [list \
    [list item "**Protein** — NewCartoon" [list marker \u2022 inline [list {bold Protein {}} [list text " — NewCartoon" {}]]]] \
    [list item "**ATP** — Licorice" [list marker \u2022 inline [list {bold ATP {}} [list text " — Licorice" {}]]]] \
    [list para "The radius of gyration is **20.84 Å**. Run `measure rgyr`:" [list inline [list {text {The radius of gyration is } {}} [list bold "20.84 Å" {}] {text {. Run } {}} {code {measure rgyr} {}} {text : {}}]]] \
    [list code "set sel \[atomselect top protein\]\nmeasure rgyr \$sel" {lang tcl}]]

test md-subset-2 {# and ## headings; ### is literal; numbered and * items} -body {
    ::vmdai::md::spans "# Title\n## Sub **b**\n### not a heading\n1. one\n2) two\n* star"
} -result [list \
    {heading Title {level 1 inline {{text Title {}}}}} \
    {heading {Sub **b**} {level 2 inline {{text {Sub } {}} {bold b {}}}}} \
    {para {### not a heading} {inline {{text {### not a heading} {}}}}} \
    {item one {marker 1. inline {{text one {}}}}} \
    {item two {marker 2. inline {{text two {}}}}} \
    [list item star [list marker \u2022 inline {{text star {}}}]]]

test md-subset-3 {paragraph lines join with one space; a blank line ends a paragraph} -body {
    ::vmdai::md::spans "line one\nline two\n\nnext"
} -result {{para {line one line two} {inline {{text {line one line two} {}}}}} {para next {inline {{text next {}}}}}}

test md-subset-4 {a fenced block keeps its bytes; no language is ""} -body {
    ::vmdai::md::spans "```\n  keep  spacing\n\n```"
} -result [list [list code "  keep  spacing\n" {lang {}}]]

test md-subset-5 {links, italics and tables stay literal text} -body {
    ::vmdai::md::spans {see [docs](http://x) and *this* | a | b |}
} -result {{para {see [docs](http://x) and *this* | a | b |} {inline {{text {see [docs](http://x) and *this* | a | b |} {}}}}}}

# Tables are not rendered (V9 non-goal); a pipe table falls back to one
# preformatted block, like a fenced block without a language (live demo).
test md-table-1 {a pipe table is one preformatted block, its lines verbatim, between paragraphs} -body {
    ::vmdai::md::spans "Intro:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter."
} -result [list {para Intro: {inline {{text Intro: {}}}}} \
    [list code "| a | b |\n|---|---|\n| 1 | 2 |" {lang {}}] \
    {para After. {inline {{text After. {}}}}}]

test md-table-2 {table lines end a paragraph and keep their indentation; a | inside a sentence stays prose} -body {
    ::vmdai::md::spans "See below:\n  | # | Residue |\n  |---|---|\nThat is a | b, not a table."
} -result [list {para {See below:} {inline {{text {See below:} {}}}}} \
    [list code "  | # | Residue |\n  |---|---|" {lang {}}] \
    {para {That is a | b, not a table.} {inline {{text {That is a | b, not a table.} {}}}}}]

test md-table-3 {plain_text (Copy) keeps table lines intact} -body {
    ::vmdai::md::plain_text "| a | b |\n|---|---|\n| 1 | 2 |"
} -result "| a | b |\n|---|---|\n| 1 | 2 |"

test md-literal-1 {an unclosed ** stays literal} -body {
    ::vmdai::md::spans "Use **bold without end"
} -result {{para {Use **bold without end} {inline {{text {Use **bold without end} {}}}}}}

test md-literal-2 {an unclosed ``` stays literal and the rest still parses} -body {
    ::vmdai::md::spans "```tcl\nset a 1\n\n- item **b**"
} -result [list \
    {para {```tcl set a 1} {inline {{text {```tcl set a 1} {}}}}} \
    [list item "item **b**" [list marker \u2022 inline {{text {item } {}} {bold b {}}}]]]

test md-literal-3 {an unclosed backtick and a lone ** stay literal} -body {
    ::vmdai::md::spans "`code without end and ** alone"
} -result {{para {`code without end and ** alone} {inline {{text {`code without end and ** alone} {}}}}}}

test md-literal-4 {empty and blank input give no spans and no error} -body {
    list [::vmdai::md::spans ""] [::vmdai::md::spans "  \n\n  "]
} -result {{} {}}

cleanupTests
