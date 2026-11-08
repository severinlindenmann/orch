import SwiftUI

/// What the banner says for one workspace in Mobile mode (words from the plan A draft).
enum MobileModeBannerState: Equatable {
    case on(pc: String)
    case unreachable(pc: String, since: String?)
    case muted(pc: String)

    var text: String {
        switch self {
        case .on(let pc): return "\(pc) is in Mobile mode"
        case .unreachable(let pc, let since):
            return since.map { "Can't reach \(pc) since \($0). Your answers wait until it is back." }
                ?? "Can't reach \(pc). Your answers wait until it is back."
        case .muted(let pc): return "Muted, but \(pc) is in Mobile mode"
        }
    }
    /// Only a reachable, unmuted computer can be turned off from here.
    var canTurnOff: Bool { if case .on = self { return true } else { return false } }

    /// nil = no banner. A muted phone shows the muted line; a computer not heard from for 5 minutes shows "Can't reach".
    static func of(_ w: Workspace, now: Date = Date(), calendar: Calendar = .current) -> MobileModeBannerState? {
        guard let m = w.mobileMode, m.on else { return nil }
        let pc = (m.machine?.isEmpty == false ? m.machine : nil) ?? w.displayName
        if w.isMuted(now: now) { return .muted(pc: pc) }
        switch w.presence(now: now) {
        case .online: return .on(pc: pc)
        case .unknown: return .unreachable(pc: pc, since: nil)
        case .lastSeen(let d):
            let f = DateFormatter(); f.calendar = calendar; f.timeZone = calendar.timeZone
            f.locale = Locale(identifier: "en_GB"); f.dateFormat = "HH:mm"
            return .unreachable(pc: pc, since: f.string(from: d))
        }
    }
}

/// Banner at the top of the chat list (`workspaceId` nil: one per workspace in Mobile mode) and of a workspace screen.
struct MobileModeBanner: View {
    @Environment(AppModel.self) private var model
    var workspaceId: String? = nil

    /// "Can't reach" depends on the clock (last call > 5 min), not only on data: re-evaluate every 15 s, because an unchanged
    /// list poll no longer redraws the screen (#244).
    var body: some View {
        TimelineView(.periodic(from: .now, by: 15)) { context in banner(now: context.date) }
    }

    @ViewBuilder
    private func banner(now: Date) -> some View {
        let items = model.workspaces
            .filter { workspaceId == nil || $0.id == workspaceId }
            .compactMap { w in MobileModeBannerState.of(w, now: now).map { (w.id, $0) } }
        ForEach(items, id: \.0) { id, state in
            HStack(spacing: 10) {
                Image(systemName: "bolt.horizontal.circle").foregroundStyle(Theme.brand).accessibilityHidden(true)
                (Text(state.text) + (state.canTurnOff ? Text(" · ") : Text(""))).themeFont(14).foregroundStyle(Theme.text)
                if state.canTurnOff {
                    Button { Task { await model.turnOffMobileMode(id) } } label: {
                        Text("Turn off").themeFont(14, .semibold).foregroundStyle(Theme.brand)
                            .frame(minHeight: 44).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).accessibilityIdentifier("mobile-mode-off-\(id)")
                }
                Spacer(minLength: 0)
            }.padding(.horizontal, 12).frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                .accessibilityElement(children: .contain).accessibilityIdentifier("mobile-mode-banner-\(id)")
        }
    }
}
