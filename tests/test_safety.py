import pytest

from spacescout.safety import Level, classify

ENV = {"SystemRoot": r"C:\Windows", "USERPROFILE": r"C:\Users\Bob"}


@pytest.mark.parametrize(
    "path,level",
    [
        ("C:\\", Level.CRITICAL),
        ("D:\\", Level.CRITICAL),
        (r"C:\Windows", Level.CRITICAL),
        (r"C:\Windows\System32\drivers", Level.CRITICAL),
        (r"C:\Windows\WinSxS", Level.CRITICAL),
        (r"C:\Windows\Temp\setup.log", Level.OK),
        (r"C:\Windows\Logs", Level.CAUTION),
        (r"C:\pagefile.sys", Level.CRITICAL),
        (r"C:\hiberfil.sys", Level.CRITICAL),
        (r"C:\Users", Level.CRITICAL),
        (r"C:\Users\Bob", Level.CRITICAL),
        (r"C:\Users\Bob\Videos", Level.OK),
        (r"C:\Users\Bob\Videos\holiday.mp4", Level.OK),
        (r"C:\Users\Bob\Downloads\setup.exe", Level.OK),
        (r"C:\Users\Bob\AppData", Level.CRITICAL),
        (r"C:\Users\Bob\NTUSER.DAT", Level.CRITICAL),
        (r"C:\Users\Bob\AppData\Local", Level.CAUTION),
        (r"C:\Users\Bob\AppData\Local\Google\Chrome", Level.CAUTION),
        (r"C:\Users\Bob\AppData\Local\Temp\abc.tmp", Level.OK),
        (r"C:\Program Files", Level.CRITICAL),
        (r"C:\Program Files\Steam", Level.CAUTION),
        (r"C:\ProgramData\Something", Level.CAUTION),
        (r"C:\Games\big.iso", Level.OK),
        (r"D:\Games\x", Level.OK),
        (r"D:\$Recycle.Bin\S-1-5", Level.CRITICAL),
        (r"D:\System Volume Information", Level.CRITICAL),
        (r"D:\Program Files\Game", Level.CAUTION),
        (r"D:\Users\old-backup", Level.OK),
    ],
)
def test_windows_rules(path, level):
    assert classify(path, windows=True, env=ENV).level == level


def test_windows_rules_case_insensitive():
    assert classify(r"c:\WINDOWS\system32", windows=True, env=ENV).level == Level.CRITICAL


def test_reasons_are_friendly():
    pr = classify(r"C:\Program Files\Steam", windows=True, env=ENV)
    assert "Settings" in pr.reason


@pytest.mark.parametrize(
    "path,level",
    [
        ("/", Level.CRITICAL),
        ("/usr", Level.CRITICAL),
        ("/usr/lib/x", Level.CAUTION),
        ("/home/bob", Level.CRITICAL),
        ("/home/bob/Videos/a.mp4", Level.OK),
        ("/home/bob/.config", Level.CAUTION),
        ("/mnt/data/stuff", Level.OK),
    ],
)
def test_posix_rules(path, level):
    assert classify(path, windows=False, env={"HOME": "/home/bob"}).level == level
