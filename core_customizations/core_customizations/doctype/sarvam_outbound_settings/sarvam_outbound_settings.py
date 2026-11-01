# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SarvamOutboundSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		org_id: DF.Data | None
		outbound_api_key: DF.Password | None
		support_agent_id: DF.Data | None
		support_agent_phone_number: DF.Data | None
		support_agent_version: DF.Int
		support_connection_id: DF.Data | None
		webhook_secret: DF.Password | None
		workspace_id: DF.Data | None
	# end: auto-generated types
