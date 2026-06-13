from krwfolio.assets import Asset
from krwfolio.exceptions import ValidationError


def validate_weights_cover_assets(assets: list[Asset], weights: dict[str, float]) -> None:
    symbols = {asset.symbol for asset in assets}
    if symbols != set(weights):
        raise ValidationError("weights must match asset symbols exactly.")

