import Foundation
import LocalAuthentication

/// Face ID (or the phone's code) before the phone answers an allow question (ORCH-1204, design choice G): a found,
/// unlocked phone cannot approve work. Normal chat never asks.
struct PersonCheck: Sendable {
    let run: @Sendable (_ reason: String) async -> Bool

    static let reason = "Confirm it is you before you allow this."

    /// Face ID, Touch ID or the phone's code. No way to check (no code set) = refused.
    static let device = PersonCheck { reason in
        let ctx = LAContext()
        var err: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &err) else { return false }
        return (try? await ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) ?? false
    }

    static let always = PersonCheck { _ in true }
    static let never = PersonCheck { _ in false }
}
