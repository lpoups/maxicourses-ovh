import os

# Le fetcher dépend de USE_CDP pour ne pas quitter immédiatement à l'import.
os.environ.setdefault("USE_CDP", "1")

from maxicourses_test import fetch_monoprix_price as monoprix


def _descriptor_fixture() -> dict:
    return {
        "brand": "Lune de Miel",
        "seed_primary_name": "Miel de fleurs liquide LUNE DE MIEL",
        "seed_primary_quantity": "500 G",
        "name": "Miel de fleurs liquide LUNE DE MIEL, 500g",
        "quantity": "500 g",
        "primary_keywords": ["Miel 500 G"],
        "secondary_keywords": ["Liquide", "LUNE", "500 G"],
        "canonical": {
            "brand": "Miel",
            "name_core": "de fleurs LUNE DE",
            "features": ["Liquide"],
            "normalized_signature": "3088545004001 miel de fleurs lune de 500.0g",
            "images": [
                "https://media.carrefour.fr/mock/03088545004001_A1L1_s01.png",
            ],
        },
    }


def test_descriptor_match_requires_strong_text():
    descriptor = _descriptor_fixture()
    candidate = monoprix.Result(
        status="OK_PARTIAL",
        title="Miel de fleurs liquide Lune de Miel 500 g",
        price="5,40 €",
        unit_price="10,80 €/kg",
        quantity="500 g",
        url="https://courses.monoprix.fr/p/miel-de-fleurs-lune-de-miel-500g",
        raw_text=(
            "Miel de fleurs liquide 500 g signé Lune de Miel. "
            "Produit simple sans format pack, vendu à l'unité."
        ),
    )

    score, plausible, extras = monoprix.evaluate_candidate(
        candidate,
        descriptor,
        negatives=[],
        seed_variant=None,
        category_tokens=["miel"],
    )

    coverage = extras["descriptor_token_coverage"]["coverage"]
    assert coverage >= monoprix.DESCRIPTOR_MATCH_COVERAGE
    assert "descriptor_coverage" not in extras["vetoes"]
    assert plausible
    assert score > 0


def test_descriptor_match_rejects_low_coverage():
    descriptor = _descriptor_fixture()
    candidate = monoprix.Result(
        status="OK_PARTIAL",
        title="Miel doux marque inconnue 500 g",
        price="4,99 €",
        unit_price="9,98 €/kg",
        quantity="500 g",
        url="https://courses.monoprix.fr/p/miel-doux-500g",
        raw_text="Miel doux 500 g, texture légère, origine Espagne.",
    )

    _, _, extras = monoprix.evaluate_candidate(
        candidate,
        descriptor,
        negatives=[],
        seed_variant=None,
        category_tokens=[],
    )

    coverage = extras["descriptor_token_coverage"]["coverage"]
    assert coverage < monoprix.DESCRIPTOR_MATCH_COVERAGE
    assert "descriptor_coverage" in extras["vetoes"]


def test_descriptor_remote_images_include_seed_variants():
    descriptor = {
        "image": "https://example.com/main.jpg",
        "canonical": {
            "images": [
                "https://example.com/canonical_a.jpg",
                "https://example.com/canonical_b.jpg",
            ]
        },
        "reference_image": "https://example.com/ref.jpg",
        "reference_images": [
            "https://example.com/ref-extra.jpg",
        ],
    }

    urls = monoprix._descriptor_remote_images(descriptor)
    assert urls == [
        "https://example.com/main.jpg",
        "https://example.com/canonical_a.jpg",
        "https://example.com/canonical_b.jpg",
        "https://example.com/ref.jpg",
        "https://example.com/ref-extra.jpg",
    ]
