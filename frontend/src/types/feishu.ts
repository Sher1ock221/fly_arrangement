export interface FeishuConfigRead {
  app_id?: string | null;
  app_secret_masked?: string | null;
  app_secret_configured: boolean;
  verification_token_masked?: string | null;
  verification_token_configured: boolean;
  encrypt_key_masked?: string | null;
  encrypt_key_configured: boolean;
  signature_check: boolean;
  enable_signature_check?: boolean;
  enable_whitelist: boolean;
  whitelist_open_ids: string;
  bot_name: string;
  public_api_base_url?: string | null;
  public_api_base_url_configured?: boolean;
  source_summary: "db" | "env" | "mixed" | string;
  config_source: "db" | "env" | "mixed" | string;
  webhook_url?: string | null;
  undo_url?: string | null;
  app_id_configured: boolean;
  whitelist_count?: number;
}

export interface FeishuConfigUpdatePayload {
  app_id?: string;
  app_secret?: string;
  verification_token?: string;
  encrypt_key?: string;
  signature_check?: boolean;
  enable_signature_check?: boolean;
  enable_whitelist?: boolean;
  whitelist_open_ids?: string;
  bot_name?: string;
  public_api_base_url?: string;
  keep_existing_app_secret?: boolean;
  keep_existing_verification_token?: boolean;
  keep_existing_encrypt_key?: boolean;
}

export interface FeishuConfigTestCheck {
  name: string;
  ok: boolean;
  message: string;
}

export interface FeishuConfigTestResult {
  ok: boolean;
  message: string;
  app_id_ok: boolean;
  app_secret_ok: boolean;
  token_ok: boolean;
  public_api_base_url_ok: boolean;
  normalized_public_api_base_url?: string | null;
  has_minimum_required_config: boolean;
  webhook_url?: string | null;
  undo_url?: string | null;
  warnings: string[];
  errors: string[];
  checks: FeishuConfigTestCheck[];
}
