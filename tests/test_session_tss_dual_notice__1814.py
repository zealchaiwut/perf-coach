from backend.services.session_tss import tss_dual_values_differ_notice


def test_notice_at_173_vs_129():
    assert tss_dual_values_differ_notice(173, 129) is True


def test_no_notice_at_100_vs_95():
    assert tss_dual_values_differ_notice(100, 95) is False