import Foundation
import Security

/// Stores the agent API token in the keychain.
public enum Keychain {
    private static let service = "de.achirus.DipAgentX"
    /// Up to 1.18 the app was called DipAgent – its token is taken over on first read.
    private static let legacyService = "de.achirus.DipAgent"

    public static func get(_ account: String) -> String? {
        if let value = read(account, service: service) { return value }
        guard let value = read(account, service: legacyService) else { return nil }
        set(value, for: account)
        return value
    }

    private static func read(_ account: String, service: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    public static func set(_ value: String, for account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        guard !value.isEmpty else { return }
        var add = query
        add[kSecValueData as String] = Data(value.utf8)
        #if os(iOS)
        // the background refresh runs while the iPhone is locked – the token must be readable then
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        #endif
        SecItemAdd(add as CFDictionary, nil)
    }
}
