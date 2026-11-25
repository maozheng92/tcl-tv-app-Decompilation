"""Store a TV still in Home Assistant Media → Image upload."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from aiohttp.web_request import FileField
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from multidict import CIMultiDict, CIMultiDictProxy

IMAGE_UPLOAD_DOMAIN = "image_upload"


def image_upload_file_field(
    filename: str, data: bytes, content_type: str
) -> FileField:
    """Wrap image bytes as the FileField Image upload's collection expects."""
    headers = CIMultiDictProxy(CIMultiDict())
    buf = BytesIO(data)
    try:
        return FileField(
            name="file",
            filename=filename,
            file=buf,
            content_type=content_type,
            headers=headers,
        )
    except TypeError:
        return FileField("file", filename, buf, content_type, headers)


async def async_image_upload_collection(hass: HomeAssistant) -> Any:
    """Return the Image upload storage collection, setting the component up if needed."""
    collection = hass.data.get(IMAGE_UPLOAD_DOMAIN)
    if collection is not None:
        return collection
    if not await async_setup_component(hass, IMAGE_UPLOAD_DOMAIN, {}):
        raise HomeAssistantError("Home Assistant Image upload is not available")
    collection = hass.data.get(IMAGE_UPLOAD_DOMAIN)
    if collection is None:
        raise HomeAssistantError("Home Assistant Image upload is not available")
    return collection


async def async_save_to_image_upload(
    hass: HomeAssistant,
    data: bytes,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    """Create one Image upload item. Returns the stored metadata dict (includes ``id``)."""
    collection = await async_image_upload_collection(hass)
    try:
        item = await collection.async_create_item(
            {"file": image_upload_file_field(filename, data, content_type)}
        )
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError(
            f"Could not save screenshot to Image upload: {err}"
        ) from err
    if not isinstance(item, dict) or not item.get("id"):
        raise HomeAssistantError("Image upload did not return an image id")
    return item
