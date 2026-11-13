import SwiftUI

/// A workspace's badge: rounded square tinted with its colour, the picked icon or else the first letter (contracts/look.md).
/// `lastSeen` adds the green online dot like the old avatar. `id` is the accessibility id suffix: `workspace-badge-<id>`.
struct WorkspaceBadge: View {
    let name: String
    var icon: String? = nil
    var color: String? = nil
    var size: CGFloat = 46
    var lastSeen: String?? = nil
    var id: String? = nil
    @Environment(AppModel.self) private var model: AppModel?

    private var shown: Look.Shown { Look.shown(icon: icon, color: color, name: name) }
    private var tone: Color { Color(hex: Look.darkHex(Self.identityColor(shown.color))) }

    /// Amber means "needs you" and teal/green mean unread, online and actions, so a badge never wears them (P06).
    /// The stored pick stays untouched; only the drawn tone moves to a nearby non-status colour.
    static let statusSwaps = ["amber": "orange", "teal": "cyan", "green": "blue", "lime": "indigo"]
    private var dotLabel: String? {
        guard let lastSeen else { return nil }
        return WorkspaceStatus.of(connection: model?.connection ?? .ok, presence: Presence.of(lastSeen: lastSeen)).dotLabel()
    }

    static func identityColor(_ token: String) -> String { statusSwaps[token] ?? token }

    var body: some View {
        let s = shown
        ZStack {
            if let icon = s.icon {
                Image("look-\(icon)").resizable().renderingMode(.template).scaledToFit()
                    .frame(width: size * (size <= 20 ? 0.75 : 0.52), height: size * (size <= 20 ? 0.75 : 0.52))
            } else {
                Text(s.letter).themeFont(size * 0.44, .semibold)
            }
        }
        .foregroundStyle(tone)
        .frame(width: size, height: size)
        .background(tone.opacity(0.18), in: RoundedRectangle(cornerRadius: size * 0.3, style: .continuous))
        .overlay(alignment: .bottomTrailing) {
            if let lastSeen {
                TimelineView(.everyMinute) { context in
                    Circle().fill(WorkspaceStatus.of(connection: model?.connection ?? .ok, presence: Presence.of(lastSeen: lastSeen, now: context.date)).isOnline ? Theme.online : Theme.muted).frame(width: 8, height: 8)
                        .overlay(Circle().stroke(Theme.surface, lineWidth: 2))
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(dotLabel.map { "Workspace icon, \($0)" } ?? "Workspace icon")
        .accessibilityIdentifier(id.map { "workspace-badge-\($0)" } ?? "workspace-badge")
        .accessibilityHidden(id == nil)
    }
}
