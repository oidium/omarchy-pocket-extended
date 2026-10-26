from pathlib import Path
import unittest


ROOT = Path(__file__).parent


class PrototypeUiStructureTests(unittest.TestCase):
    def test_workspace_uses_final_compact_card_geometry(self):
        source = (ROOT / "ExtendedPanel.qml").read_text()
        self.assertIn("workspaceHeight: card.height", source)
        self.assertIn("workspaceY: card.y", source)

    def test_extended_notification_delegate_hides_expansion_control(self):
        source = (ROOT / "Panel.qml").read_text()
        delegate = source[source.index("Repeater {\n              id: notificationRepeater"):]
        self.assertIn("showExpandControl: false", delegate)

    def test_compact_preview_retains_its_bounded_viewport(self):
        source = (ROOT / "Panel.qml").read_text()
        self.assertIn("height:Math.min(previews.implicitHeight,Style.space(150))", source)

    def test_history_button_activity_requires_visible_panel(self):
        source = (ROOT / "Panel.qml").read_text()
        self.assertIn('historyButtonActive: opened && (workspaceContext === "history" || workspaceContext === "thread")', source)
        self.assertIn('selected:root.historyButtonActive', source)
        self.assertIn('historyNavigation.hasCursor=false', source)
        self.assertNotIn('historyNavigation.forceActiveFocus()', source)
        self.assertIn('smsEditor.resetContactView()', source)


if __name__ == "__main__":
    unittest.main()
