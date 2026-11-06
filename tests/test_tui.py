import asyncio

from screen_clicker import config
from screen_clicker.engine import Engine
from screen_clicker.tui.app import ScreenClickerApp


class IdleEngine(Engine):
    def start(self) -> None:
        pass


def test_mouse_clicks_and_tab_switching_do_not_crash(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = config.load(path)

    async def run() -> None:
        app = ScreenClickerApp(IdleEngine(cfg, tmp_path), cfg, path)
        async with app.run_test(size=(140, 45)) as pilot:
            for selector in ("#pill", "#logo", "#c-scans", "#log", "#history"):
                await pilot.click(selector)
            for tab in ("targets", "focus", "preview", "settings", "dash"):
                await pilot.click(f"#--content-tab-{tab}")
                await pilot.pause()
                assert app.query_one("TabbedContent").active == tab
            await pilot.press("q")

    asyncio.run(run())
