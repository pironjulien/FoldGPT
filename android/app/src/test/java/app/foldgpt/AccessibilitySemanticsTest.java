package app.foldgpt;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.Test;
import static org.junit.Assert.*;
import app.foldgpt.FoldAccessibilityService.SemanticBudget;
import app.foldgpt.FoldAccessibilityService.SemanticNode;

public final class AccessibilitySemanticsTest {
    private static final Map<String, Object> ORIGINAL = Map.of(
            "text", "7", "description", "Seven", "hint", "", "password", false,
            "bounds", List.of(0, 0, 80, 80), "actions", List.of(List.of(16, "Click")),
            "flags", List.of(true, true, false, false));

    private static SemanticNode node(String identity, String parent, Map<String, Object> properties) {
        return new SemanticNode(identity, parent, properties);
    }

    private static boolean same(List<SemanticNode> before, List<SemanticNode> after) {
        return FoldAccessibilityService.sameSemanticTree(before, true, after, true);
    }

    @Test public void repeatedUnchangedTreeDoesNotRequireReplacingItsIdentities() {
        List<SemanticNode> original = List.of(node("root", null, Map.of()), node("button", "token:0", ORIGINAL));
        for (int i = 0; i < 64; i++) {
            List<SemanticNode> refreshed = List.of(node(new String("root"), null, Map.of()),
                    node(new String("button"), "token:0", new LinkedHashMap<>(ORIGINAL)));
            assertTrue(same(original, refreshed));
        }
    }

    @Test public void eachChangedContentGeometryActionAndPasswordPropertyIsRejected() {
        Map<String, Object> changes = Map.of(
                "text", "8", "description", "Eight", "hint", "Updated", "password", true,
                "bounds", List.of(1, 0, 81, 80), "actions", List.of(List.of(32, "Long click")),
                "flags", List.of(true, false, false, false));
        List<SemanticNode> original = List.of(node("button", null, ORIGINAL));
        changes.forEach((key, value) -> {
            Map<String, Object> properties = new LinkedHashMap<>(ORIGINAL);
            properties.put(key, value);
            assertFalse(key, same(original, List.of(node("button", null, properties))));
        });
    }

    @Test public void replacementAtIdenticalBoundsAndTextDoesNotInheritTheObservedNodeId() {
        assertFalse(same(List.of(node("old-provider-id", null, ORIGINAL)),
                List.of(node("new-provider-id", null, ORIGINAL))));
    }

    @Test public void hierarchyOrderingAdditionAndRemovalArePartOfTheComparison() {
        SemanticNode root = node("root", null, Map.of());
        SemanticNode first = node("first", "token:0", ORIGINAL);
        SemanticNode second = node("second", "token:0", ORIGINAL);
        List<SemanticNode> original = List.of(root, first, second);
        assertFalse(same(original, List.of(root, second, first)));
        assertFalse(same(original, List.of(root, first)));
        assertFalse(same(original, List.of(root, first, second, node("third", "token:0", ORIGINAL))));
        assertFalse(same(original, List.of(root, first, node("second", "token:1", ORIGINAL))));
    }

    @Test public void identicalIncompletePrefixCannotAuthorizeAnAction() {
        List<SemanticNode> nodes = List.of(node("root", null, ORIGINAL));
        assertFalse(FoldAccessibilityService.sameSemanticTree(nodes, false, nodes, true));
        assertFalse(FoldAccessibilityService.sameSemanticTree(nodes, true, nodes, false));
        assertFalse(FoldAccessibilityService.sameSemanticTree(nodes, false, nodes, false));
    }

    @Test public void capturedPropertiesCannotBeChangedThroughTheirSourceMap() {
        Map<String, Object> properties = new LinkedHashMap<>(ORIGINAL);
        SemanticNode captured = node("button", null, properties);
        properties.put("password", true);
        assertEquals(false, captured.properties().get("password"));
    }

    @Test public void changedSuffixBeyondPresentationLimitIsStillCompared() {
        String common = "a".repeat(4096);
        SemanticBudget before = new SemanticBudget(), after = new SemanticBudget();
        String original = before.text(common + "first");
        String current = after.text(common + "second");
        assertTrue(before.complete && after.complete);
        assertNotEquals(original, current);
    }

    @Test public void aggregateTextBudgetIsExactAndCannotPretendTruncationIsComplete() {
        SemanticBudget budget = new SemanticBudget();
        assertEquals(65_536, budget.text("a".repeat(65_536)).length());
        assertTrue(budget.complete);
        assertEquals("", budget.text("b"));
        assertFalse(budget.complete);
        SemanticBudget oversized = new SemanticBudget();
        assertEquals(65_536, oversized.text("x".repeat(65_537)).length());
        assertFalse(oversized.complete);
    }

    @Test public void textReaderNeverMaterializesAnUnboundedCharSequence() {
        CharSequence oversized = new CharSequence() {
            public int length() { return Integer.MAX_VALUE; }
            public char charAt(int index) { return 'x'; }
            public CharSequence subSequence(int start, int end) {
                assertEquals(0, start);
                assertTrue(end <= 65_536);
                return "x".repeat(end - start);
            }
            public String toString() { throw new AssertionError("Unbounded materialization"); }
        };
        SemanticBudget budget = new SemanticBudget();
        assertEquals(65_536, budget.text(oversized).length());
        assertFalse(budget.complete);
    }
}
