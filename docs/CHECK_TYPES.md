# CopCat Check Types Reference

## Static (no execution)

| Type | Params | What it checks |
|---|---|---|
| `exists_class` | `name` | class exists (by exact or bound name) |
| `exists_method` | `class`, `method` | method defined in class |
| `method_exists` | `class`, `methods` (list) | all listed methods defined |
| `class_exists` | `classes` (list) | all listed classes exist |
| `has_attrs` / `instance_attrs` | `class`, `attrs` (list) | instance attributes assigned |
| `has_decorator` | `class`, `method`, `decorator` | method has @decorator |
| `calls_super` | `class`, `method` | super() called in method |
| `base_class` | `class`, `base` | class inherits from base |
| `name_mangled_attr` | `class`, `attr` | `self.__attr` assignment present |
| `forbidden_pattern` | `pattern`, `scope`, optional `include_comments` | regex NOT found in scoped source |
| `regex_present` | `pattern`, optional `include_comments` | regex found in code |
| `comment_regex_present` | `pattern`, `label` | regex found in comments/docstrings |
| `min_lines` | `count` | minimum non-blank line count |
| `forbidden_import_or_usage` | `target` (dotted name), `scope` | import/usage of target not present |
| `forbidden_instance_attrs` | `class`, `attrs` (list) | none of the attrs assigned on self |
| `exception_hierarchy` | `base`, `subclasses` (list) | all subclasses transitively inherit base |
| `ast_uses_class` | `function`, `required_class` | function body references the class |

## Dynamic (sandboxed run)

| Type | Params | What it checks |
|---|---|---|
| `runs_clean` | — | submission executes without crash |
| `stdout_contains` | `text` | output contains literal text |
| `stdout_regex` / `stdout_contains_pattern` | `pattern` | output matches regex |
| `dynamic_execution` | `expected_action_sequence` (list) | actions appear in order in output log |

## Functional (sandboxed probes)

| Type | Params | What it checks |
|---|---|---|
| `functional` | `construct`, `call`, `expect` | construct + call works as expected |
| `functional_call_raises` | `target`, `methods` (list), `expected_exception` | each method raises the expected exception |
| `functional_call_returns` | `function`, `args`, `expected_match`, `expected_reason_contains` | return value matches at index; reason contains substrings |
| `functional_property_test` | `target`, `sequence` (list of steps) | lifecycle/property sequence holds |

Probe `expect` values: `ok`, `raises_any`, `raises:ExceptionName`, `truthy`.

Sequence step keys: `{method: args}` calls; `{assert_attr: val}` asserts
`obj.attr() == val`; `{initial_X: val}` sets `obj.X`; `{step_N_percept: val}`
calls `update_state(val)`; `{step_N_action: val}` asserts `act(percept) == val`;
`{expected_X_step_N: {k: v}}` asserts `obj.X` dict contains k→v.
