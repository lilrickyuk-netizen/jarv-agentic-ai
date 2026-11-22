# MYCO's local Vault (spec Phase 3 "Vault integration"; Vault 2.1.1 per section 40). Data on its own volume, so a
# restart keeps every secret; listens on MYCO's private network only, without TLS (no route in from anywhere else).
storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr      = "http://myco-vault:8200"
disable_mlock = true
ui            = false
