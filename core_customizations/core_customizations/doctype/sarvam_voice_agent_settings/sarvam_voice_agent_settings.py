# Copyright (c) 2026, Vinod Kumar K and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SarvamVoiceAgentSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enable_call_logging: DF.Check
		enabled: DF.Check
		org_id: DF.Data | None
		outbound_api_key: DF.Password | None
		s3_access_key_id: DF.Data | None
		s3_bucket: DF.Data | None
		s3_endpoint_url: DF.Data | None
		s3_inbound_path_prefix: DF.Data | None
		s3_outbound_path_prefix: DF.Data | None
		s3_region: DF.Data | None
		s3_secret_access_key: DF.Password | None
		support_agent_id: DF.Data | None
		support_agent_phone_number: DF.Data | None
		support_agent_version: DF.Int
		support_connection_id: DF.Data | None
		webhook_secret: DF.Password | None
		workspace_id: DF.Data | None
	# end: auto-generated types
