from __future__ import annotations

import json

from backend.app.media.video_urls import normalize_xhs_video_url
from backend.app.store.models import Image
from backend.app.xhs.parser import (
    normalize_asset_url,
    normalize_video,
)


def test_normalize_webpic_url_to_stable_image_url():
    assert (
        normalize_asset_url(
            "https://sns-webpic-qc.xhscdn.com/202605271417/597aa4c3f6b8d5436ff72e206dde5813/"
            "1000g008285kpvt8fs0005otqfov9t2bf30gkprg!nd_dft_wlteh_webp_3"
        )
        == "https://sns-img-qc.xhscdn.com/1000g008285kpvt8fs0005otqfov9t2bf30gkprg!nd_dft_wlteh_webp_3"
    )


def test_normalize_bare_sns_img_url_adds_display_suffix():
    assert (
        normalize_asset_url("https://sns-img-qc.xhscdn.com/1000g008285kpvt8fs0005otqfov9t2bf30gkprg")
        == "https://sns-img-qc.xhscdn.com/1000g008285kpvt8fs0005otqfov9t2bf30gkprg!nd_dft_wlteh_webp_3"
    )


def test_normalize_webpic_spectrum_url_preserves_spectrum_path():
    assert (
        normalize_asset_url(
            "http://sns-webpic-qc.xhscdn.com/202605281941/0019c3d59665a4ad1d5110407186dd29/"
            "spectrum/1000g0k026damv8qfm0005n31aed7a4c4pqh3ln0!nd_dft_wlteh_jpg_3"
        )
        == "https://sns-img-qc.xhscdn.com/spectrum/1000g0k026damv8qfm0005n31aed7a4c4pqh3ln0!nd_dft_wlteh_webp_3"
    )


def test_normalize_video_uses_stream_url_and_metadata():
    video = normalize_video(
        {
            "media": {
                "stream": {
                    "h264": [
                        {
                            "masterUrl": (
                                "https://sns-video-v3.xhscdn.com/stream/110/258/"
                                "01e4c23defe7ef20010370038996c7d645_258.mp4?sign=abc&t=6a1de89d"
                            ),
                            "width": 720,
                            "height": 1280,
                            "duration": 12000,
                        }
                    ]
                }
            },
        },
        [Image(url="https://sns-img-qc.xhscdn.com/poster!nd_dft_wlteh_webp_3")],
    )

    assert video is not None
    assert video.url == "https://sns-video-bd.xhscdn.com/stream/110/258/01e4c23defe7ef20010370038996c7d645_258.mp4"
    assert video.width == 720
    assert video.height == 1280
    assert video.duration == 12


def test_normalize_video_reads_stream_from_media_v2():
    video = normalize_video(
        {
            "mediaV2": json.dumps(
                {
                    "video": {"width": 1080, "height": 1920},
                    "stream": {"h264": [{"masterUrl": "https://sns-video-qc.xhscdn.com/nested-stream-url"}]},
                }
            )
        },
        [],
    )

    assert video is not None
    assert video.url == "https://sns-video-qc.xhscdn.com/nested-stream-url"
    assert video.width == 1080
    assert video.height == 1920


def test_normalize_xhs_video_url_uses_clean_playback_host():
    raw_url = (
        "https://sns-video-v3.xhscdn.com/stream/110/258/"
        "01e4c23defe7ef20010370038996c7d645_258.mp4?sign=abc&t=6a1de89d"
    )

    assert (
        normalize_xhs_video_url(raw_url)
        == "https://sns-video-bd.xhscdn.com/stream/110/258/01e4c23defe7ef20010370038996c7d645_258.mp4"
    )
