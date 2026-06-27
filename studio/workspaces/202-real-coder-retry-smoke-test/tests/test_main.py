import pytest
from app.main import main
def test_main(capsys):
    main()
    captured = capsys.readouterr()
    assert captured.out == "hello from ai studio\n"