import Foundation
import UIKit

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
              RelayURL.isSafe(relay),
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

/// Where the phone may send its token. ATS does not cover IP addresses or `.local` names, so the app checks itself:
/// https only, plain http just for this device's own loopback (the Simulator e2e talks to a local relay).
enum RelayURL {
    static func isSafe(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased(), !host.isEmpty else { return false }
        switch url.scheme?.lowercased() {
        case "https": return true
        case "http": return ["127.0.0.1", "localhost", "::1"].contains(host)
        default: return false
        }
    }
}

/// One wording for where an invitation comes from, used on every invitation screen.
enum InviteWording {
    static let source = "You get an invitation from orch on your computer."
    static let stepsTitle = "Get an invitation"
    static let steps = [
        "On your computer, open the orch portal. orch must be set up and running there.",
        "Choose Add phone and pick the workspaces you want on this phone.",
        "Scan the QR code it shows, or send the link to this phone and paste it here.",
    ]
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

/// Reads an invitation link from the clipboard. A valid one is taken off the clipboard right away: the code works
/// once, and leaving it there lets other apps (and Universal Clipboard on nearby devices) read it.
enum InvitePaste {
    @MainActor static func take(from pasteboard: UIPasteboard = .general) -> String? {
        guard let value = pasteboard.string, (try? PairingLink(value)) != nil else { return nil }
        if pasteboard.string == value { pasteboard.items = [] }
        return value
    }
}
