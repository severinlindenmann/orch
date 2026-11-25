import Foundation

/// `orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_<22 chars>`
struct PairingLink: Equatable, Sendable {
    let relay: URL
    let code: String

    init(relay: URL, code: String) { self.relay = relay; self.code = code }

    init(_ text: String) throws {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "orch", url.host == "pair",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              let relayText = items.first(where: { $0.name == "relay" })?.value,
              let relay = URL(string: relayText), let host = relay.host, !host.isEmpty,
              ["https", "http"].contains(relay.scheme ?? ""),
              let code = items.first(where: { $0.name == "code" })?.value,
              code.hasPrefix("pc_"), code.count > 6
        else { throw RelayError.badLink }
        self.relay = relay; self.code = code
    }

    var host: String { relay.host ?? relay.absoluteString }

    /// The sample invitation of the mock relay.
    static let sample = PairingLink(relay: URL(string: "https://relay.severin.io")!, code: "pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V")
    var link: String {
        "orch://pair?relay=\(relay.absoluteString.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")&code=\(code)"
    }
}

/// One wording for where an invitation comes from, used on every invitation screen (setup and Add workspace).
/// A recipient gets a new invitation from the person who invited them; only the admin can create one (Add phone on
/// the relay admin page), so those steps are kept apart and named for the admin.
enum InviteWording {
    static let source = "Ask the person who set up orch for you to send an invitation."
    static let stepsTitle = "If you are the admin"
    static let steps = [
        "Open the relay admin page on your private network.",
        "Choose Add phone and pick the workspaces for this phone.",
        "Scan the QR code it shows, or send the link to this phone and paste it here.",
    ]
    static let askForNew = "Ask the person who invited you for a new one."
    static let expired = "This invitation has expired or was already used. \(askForNew)"
    static let notValid = "This invitation is not valid. \(askForNew)"
    static let badLink = "That link does not look right. Check you copied the whole link, or ask the person who invited you for a new one."
}

/// Why the QR scanner cannot scan.
enum ScannerProblem: Equatable {
    case denied, restricted, noCamera, failed
    var text: String {
        switch self {
        case .denied: "orch can't use the camera. Allow it in Settings, or paste the link instead."
        case .restricted: "The camera is blocked on this phone. Paste the link instead."
        case .noCamera: "This device has no camera. Paste the link instead."
        case .failed: "The camera didn't start. Close and try again, or paste the link instead."
        }
    }
}
