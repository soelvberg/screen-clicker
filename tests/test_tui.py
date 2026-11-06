import asyncio

from screen_clicker import config
from screen_clicker.config import Region, Target
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


def test_add_target_with_region_and_set_region(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = config.load(path)

    async def run() -> None:
        app = ScreenClickerApp(IdleEngine(cfg, tmp_path), cfg, path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.press("f2")
            app.query_one("#target-input").value = "play"
            app.query_one("#region-input").value = "60,75,40,25"
            await pilot.click("#target-add")
            await pilot.pause()
            assert config.load(path).targets == [Target("play", region=Region(60, 75, 40, 25))]

            app.query_one("#region-input").value = ""
            await pilot.click("#target-region")
            await pilot.pause()
            assert config.load(path).targets == [Target("play")]

            app.query_one("#region-input").value = "nope"
            await pilot.click("#target-region")
            await pilot.pause()
            assert config.load(path).targets == [Target("play")]

    asyncio.run(run())
