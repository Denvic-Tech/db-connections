from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, TypeAlias

from astroid import nodes
from pylint.checkers import BaseChecker
from pylint.typing import MessageDefinitionTuple

if TYPE_CHECKING:
    from pylint.lint import PyLinter


CollectionNode: TypeAlias = nodes.List | nodes.Tuple | nodes.Set | nodes.Dict


class NoLargeInlineCollectionsChecker(BaseChecker):
    name = "no-large-inline-collections"

    msgs: ClassVar[dict[str, MessageDefinitionTuple]] = {
        "W5101": (
            "Inline %s literal with %s items detected; calculate it or move it to a named constant",
            "large-inline-collection",
            "Used when list/tuple/set/dict literals with too many items are used inline.",
        ),
    }

    options = (
        (
            "max-inline-collection-items",
            {
                "default": 2,
                "type": "int",
                "metavar": "<int>",
                "help": "Maximum allowed number of items in inline collection literals.",
            },
        ),
        (
            "large-inline-collection-types",
            {
                "default": ("list", "tuple", "set", "dict"),
                "type": "csv",
                "metavar": "<list,tuple,set,dict>",
                "help": "Collection literal types checked by large-inline-collection.",
            },
        ),
        (
            "large-inline-collection-ignore-contexts",
            {
                "default": (
                    "assignment",
                    "assignment-target",
                    "type-annotation",
                ),
                "type": "csv",
                "metavar": "<assignment,assignment-target,type-annotation,constant-assignment>",
                "help": (
                    "Contexts where large inline collection literals are allowed. "
                    "Available: assignment, assignment-target, type-annotation, constant-assignment."
                ),
            },
        ),
    )

    def visit_list(self, node: nodes.List) -> None:
        self._check_collection(node)

    def visit_tuple(self, node: nodes.Tuple) -> None:
        self._check_collection(node)

    def visit_set(self, node: nodes.Set) -> None:
        self._check_collection(node)

    def visit_dict(self, node: nodes.Dict) -> None:
        self._check_collection(node)

    def _check_collection(self, node: CollectionNode) -> None:
        collection_type = self._collection_type(node)

        if collection_type not in self._enabled_collection_types():
            return

        if self._should_ignore_by_context(node):
            return

        size = self._collection_size(node)
        max_size = self.linter.config.max_inline_collection_items

        if size <= max_size:
            return

        self.add_message(
            "large-inline-collection",
            node=node,
            args=(collection_type, size),
        )

    def _should_ignore_by_context(self, node: CollectionNode) -> bool:
        ignored_contexts = self._ignored_contexts()
        return (
            ("assignment" in ignored_contexts and self._is_inside_assignment_value(node))
            or (
                "constant-assignment" in ignored_contexts
                and self._is_inside_constant_assignment(node)
            )
            or ("assignment-target" in ignored_contexts and self._is_assignment_target(node))
            or ("type-annotation" in ignored_contexts and self._is_inside_type_annotation(node))
        )

    def _enabled_collection_types(self) -> set[str]:
        return self._normalize_csv_option(
            self.linter.config.large_inline_collection_types
        )

    def _ignored_contexts(self) -> set[str]:
        return self._normalize_csv_option(
            self.linter.config.large_inline_collection_ignore_contexts
        )

    @staticmethod
    def _normalize_csv_option(value: object) -> set[str]:
        items = value.split(",") if isinstance(value, str) else value

        return {
            str(item).strip().lower()
            for item in items
            if str(item).strip()
        }

    @staticmethod
    def _collection_type(node: CollectionNode) -> str:
        if isinstance(node, nodes.List):
            return "list"
        if isinstance(node, nodes.Tuple):
            return "tuple"
        if isinstance(node, nodes.Set):
            return "set"
        if isinstance(node, nodes.Dict):
            return "dict"

        raise TypeError(f"Unsupported collection node: {type(node)!r}")

    @staticmethod
    def _collection_size(node: CollectionNode) -> int:
        if isinstance(node, nodes.Dict):
            return len(node.items)

        return len(node.elts)

    def _is_inside_assignment_value(self, node: CollectionNode) -> bool:
        """
        Ignore collection literals used as assignment values:

            fields = ("name", "driver", "properties")
            self.fields = ("name", "driver", "properties")
            fields: tuple[str, ...] = ("name", "driver", "properties")

        But do not treat assignment targets as values:

            a, b, c = row
        """
        current: nodes.NodeNG = node
        parent = node.parent

        while parent is not None:
            if isinstance(parent, nodes.Assign):
                return not any(
                    self._contains_node(target, node)
                    for target in parent.targets
                )

            if isinstance(parent, nodes.AnnAssign):
                return not self._contains_node(parent.target, node)

            if isinstance(parent, nodes.NamedExpr):
                return not self._contains_node(parent.target, node)

            current = parent
            parent = current.parent

        return False

    def _is_inside_constant_assignment(self, node: CollectionNode) -> bool:
        """
        Ignore only UPPER_CASE assignments:

            FIELDS = ("name", "driver", "properties")

        But still warn on:

            fields = ("name", "driver", "properties")
        """
        current: nodes.NodeNG = node
        parent = node.parent

        while parent is not None:
            if isinstance(parent, nodes.Assign):
                if any(self._contains_node(target, node) for target in parent.targets):
                    return False

                return any(
                    self._is_constant_assign_target(target)
                    for target in parent.targets
                )

            if isinstance(parent, nodes.AnnAssign):
                if self._contains_node(parent.target, node):
                    return False

                return self._is_constant_assign_target(parent.target)

            current = parent
            parent = current.parent

        return False

    def _is_assignment_target(self, node: CollectionNode) -> bool:
        """
        Ignore unpacking targets:

            a, b, c = row

            for a, b, c in rows:
                ...
        """
        current: nodes.NodeNG = node
        parent = node.parent

        while parent is not None:
            if isinstance(parent, nodes.Assign):
                return any(
                    self._contains_node(target, node)
                    for target in parent.targets
                )

            if isinstance(parent, nodes.AnnAssign):
                return self._contains_node(parent.target, node)

            if isinstance(parent, nodes.For):
                return self._contains_node(parent.target, node)

            current = parent
            parent = current.parent

        return False

    @staticmethod
    def _is_constant_assign_target(node: nodes.NodeNG) -> bool:
        if isinstance(node, nodes.AssignName):
            return node.name.isupper()

        return False

    def _is_inside_type_annotation(self, node: CollectionNode) -> bool:
        """
        Avoid false positives:

            value: Literal["a", "b", "c"]

            def foo() -> tuple[int, str, bool]:
                ...
        """
        current: nodes.NodeNG = node
        parent = node.parent

        while parent is not None:
            if self._annotation_attr_contains(parent, node):
                return True

            current = parent
            parent = current.parent

        return False

    def _annotation_attr_contains(
        self,
        parent: nodes.NodeNG,
        node: nodes.NodeNG,
    ) -> bool:
        annotation_attrs = (
            "annotation",
            "returns",
            "type_annotation",
            "varargannotation",
            "kwargannotation",
            "annotations",
            "posonlyargs_annotations",
            "kwonlyargs_annotations",
        )

        for attr_name in annotation_attrs:
            value = getattr(parent, attr_name, None)

            if isinstance(value, nodes.NodeNG) and self._contains_node(value, node):
                return True

            if isinstance(value, list | tuple):
                for item in value:
                    if isinstance(item, nodes.NodeNG) and self._contains_node(item, node):
                        return True

        return False

    @staticmethod
    def _contains_node(root: nodes.NodeNG, needle: nodes.NodeNG) -> bool:
        if root is needle:
            return True

        return any(
            NoLargeInlineCollectionsChecker._contains_node(child, needle)
            for child in root.get_children()
        )


def register(linter: PyLinter) -> None:
    linter.register_checker(NoLargeInlineCollectionsChecker(linter))
