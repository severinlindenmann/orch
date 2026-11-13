import SwiftUI

/// Words and colours for a computer in Mobile mode.
enum MobileModeBannerState: Equatable {
    case on(pc: String)
    case unreachable(pc: String, since: String?)
    case muted(pc: String)

    var text: String {
        switch self {
        case .on(let pc): return "\(pc) is away · questions come to your phone"
        case .unreachable(let pc, let since):
            return since.map { "\(pc) · Can't reach since \($0)" }
                ?? "\(pc) · Can't reach"
        case .muted(let pc): return "\(pc) is away · questions muted"
        }
    }
    // Tints are layered over Theme.surface by the banner.
    static let onBackground = Theme.brand.opacity(0.22)
    static let unreachableBackground = Theme.warn.opacity(0.18)
    static let mutedBackground = Theme.surface3
    static let onBorder = Theme.brand.opacity(0.5)

    var background: Color {
        switch self {
        case .on: Self.onBackground
        case .unreachable: Self.unreachableBackground
        case .muted: Self.mutedBackground
        }
    }

    var dotColor: Color {
        switch self {
        case .on: Theme.brand
        case .unreachable: Theme.warn
        case .muted: Theme.muted
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

/// Mobile mode banner below the workspace header.
struct MobileModeBanner: View {
    @Environment(AppModel.self) private var model
    var workspaceId: String? = nil

    /// "Can't reach" depends on the clock (last call > 5 min), not only on data: re-evaluate every 15 s, because an unchanged
    /// list poll no longer redraws the screen (#244).
    /// Mobile mode on for a workspace in scope. Decided without the clock, so a workspace with Mobile mode off adds no view at all
    /// (an empty TimelineView is still an empty List row with its insets and a gap in a stack).
    private var anyOn: Bool {
        model.workspaces.contains { (workspaceId == nil || $0.id == workspaceId) && $0.mobileMode?.on == true }
    }

    var body: some View {
        if anyOn {
            TimelineView(.periodic(from: .now, by: 15)) { context in banner(now: context.date) }
        }
    }

    @ViewBuilder
    private func banner(now: Date) -> some View {
        let items = model.workspaces
            .filter { workspaceId == nil || $0.id == workspaceId }
            .compactMap { w in MobileModeBannerState.of(w, now: now).map { (w.id, $0) } }
        ForEach(items, id: \.0) { id, state in
            HStack(spacing: 10) {
                Circle().fill(state.dotColor).frame(width: 7, height: 7).accessibilityHidden(true)
                Text(state.text).themeFont(13).foregroundStyle(Theme.text)
                    .lineLimit(1).minimumScaleFactor(0.85)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if state.canTurnOff {
                    Button { Task { await model.turnOffMobileMode(id) } } label: {
                        Text("Turn off").themeFont(13, .bold).foregroundStyle(Theme.brand)
                            .fixedSize(horizontal: true, vertical: false).frame(minHeight: 44).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).accessibilityIdentifier("mobile-mode-off-\(id)")
                }
            }.padding(.horizontal, 12).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .background {
                    RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).fill(Theme.surface)
                    RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).fill(state.background)
                }
                .overlay {
                    if state.canTurnOff {
                        RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)
                            .stroke(MobileModeBannerState.onBorder, lineWidth: 1)
                    }
                }
                .accessibilityElement(children: .contain).accessibilityIdentifier("mobile-mode-banner-\(id)")
        }
    }
}
