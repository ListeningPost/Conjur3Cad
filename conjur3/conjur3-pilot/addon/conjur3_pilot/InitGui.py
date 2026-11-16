import FreeCAD
import FreeCADGui as Gui


class Conjur3Workbench(Workbench):
    MenuText = "Conjur3"
    ToolTip = "Live RPC bridge that lets an external MCP client (Claude Code) drive the running FreeCAD GUI."

    def Initialize(self):
        from rpc_server import rpc_server  # noqa: F401 — registers commands

        commands = [
            "Conjur3_Start_Server",
            "Conjur3_Stop_Server",
            "Conjur3_Toggle_Auto_Start",
            "Conjur3_Toggle_Remote",
            "Conjur3_Configure_Allowed_IPs",
        ]
        self.appendToolbar("Conjur3", commands)
        self.appendMenu("Conjur3", commands)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def ContextMenu(self, recipient):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(Conjur3Workbench())


def _auto_start_pilot():
    try:
        from rpc_server import rpc_server

        settings = rpc_server.load_settings()
        if settings.get("auto_start_rpc", True):  # Conjur3 default: auto-start ON
            msg = rpc_server.start_rpc_server()
            FreeCAD.Console.PrintMessage(f"[Conjur3] Auto-start: {msg}\n")

        # Conjur3 link — the connector, in-process (pure Python, no Node).
        # Runs in a background thread for the life of this FreeCAD session and
        # bridges the hosted relay to this RPC server. Works under snap/flatpak
        # confinement because nothing external is spawned.
        try:
            import conjur3_link

            FreeCAD.Console.PrintMessage(
                f"[Conjur3] {conjur3_link.start_link(settings)}\n"
            )
            conjur3_link.register_shutdown()
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[Conjur3] Conjur3 link skipped: {e}\n")
    except Exception as e:
        FreeCAD.Console.PrintWarning(f"[Conjur3] Auto-start failed: {e}\n")


from PySide import QtCore  # noqa: E402

QtCore.QTimer.singleShot(0, _auto_start_pilot)
