"""Profile command handlers backed by public profile DTOs."""

from __future__ import annotations

from ...api.contracts import ProfileCommand, ProfileCommandKind, ProfileQuery
from .base import CommandArgumentError, CommandContext, CommandResult, api_failure


def _key_value(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise CommandArgumentError("expected key=value")
    key, content = value.split("=", 1)
    if not key or not content:
        raise CommandArgumentError("key=value must contain both key and value")
    return key, content


class ProfileHandler:
    def handle(self, args: tuple[str, ...], context: CommandContext) -> CommandResult:
        if not args or args[0] == "list":
            if args not in ((), ("list",)):
                raise CommandArgumentError("invalid profile list arguments")
            result = context.api.get_profile(ProfileQuery())
            if not result.is_success:
                return api_failure(result, prefix="Profile unavailable: ")
            assert result.value is not None
            return CommandResult(
                "\n".join(
                    f"{item.item_id}: {item.key}={item.value} [{item.sensitivity}] confirmed"
                    for item in result.value
                )
                or "No confirmed profile items."
            )

        operation = args[0]
        if operation == "add" and len(args) in {3, 4}:
            key, value = _key_value(args[1])
            result = context.api.change_profile(
                ProfileCommand(
                    ProfileCommandKind.ADD,
                    item_id=args[2],
                    key=key,
                    value=value,
                    sensitivity=args[3] if len(args) == 4 else "local",
                )
            )
            if not result.is_success:
                return api_failure(result, prefix="Profile update failed: ")
            return CommandResult(f"Profile item confirmed: {args[2]}")

        if operation == "correct" and len(args) in {3, 4}:
            key, value = _key_value(args[2])
            result = context.api.change_profile(
                ProfileCommand(
                    ProfileCommandKind.CORRECT,
                    item_id=args[1],
                    key=key,
                    value=value,
                    sensitivity=args[3] if len(args) == 4 else "local",
                )
            )
            if not result.is_success:
                return api_failure(result, prefix="Profile update failed: ")
            return CommandResult(f"Profile item corrected: {args[1]}")

        if operation == "delete" and len(args) == 2:
            result = context.api.change_profile(
                ProfileCommand(ProfileCommandKind.DELETE, item_id=args[1])
            )
            if not result.is_success:
                return api_failure(result, prefix="Profile update failed: ")
            assert result.value is not None
            return CommandResult(
                "Profile item deleted." if result.value else "Profile item not found."
            )

        raise CommandArgumentError(
            "expected list, add key=value item-id [sensitivity], "
            "correct item-id key=value [sensitivity], or delete item-id"
        )
