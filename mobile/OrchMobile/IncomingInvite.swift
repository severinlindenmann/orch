import Foundation

/// An invitation opened on a phone that is already paired (ORCH-2127). Its code goes only to the server this phone is
/// paired with: same scheme, host and port. Any other invitation is shown, never sent anywhere.
enum IncomingInvite {
    static func sameOrigin(_ a: URL, _ b: URL) -> Bool {
        guard let sa = a.scheme?.lowercased(), let sb = b.scheme?.lowercased(), sa == sb,
              let ha = a.host?.lowercased(), let hb = b.host?.lowercased(), !ha.isEmpty, ha == hb
        else { return false }
        return port(a, sa) == port(b, sb)
    }
    private static func port(_ url: URL, _ scheme: String) -> Int? { url.port ?? (scheme == "https" ? 443 : scheme == "http" ? 80 : nil) }

    static let otherServerTitle = "This invitation is for another server"
    static let otherServer = "It was not used, and this phone stays connected as it is. Ask for an invitation from the orch this phone already uses."
}
