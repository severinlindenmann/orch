import SwiftUI

/// Tool warnings on top of a workspace (contracts/tool-alert.md, mockup 5b): one row per tool login, connection or key
/// that runs out soon or stopped working, until the workspace says it works again. The phone only tells; the person
/// renews on the computer. Plain text only.
struct ToolAlertBanner: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dynamicTypeSize) private var typeSize
    var workspaceId: String

    static func tint(_ tone: String) -> Color { tone == "warn" ? Theme.warn : Theme.danger }

    var body: some View {
        ForEach(ToolAlertRules.rows(model.messages, workspaceId: workspaceId)) { row in
            HStack(alignment: .top, spacing: 10) {
                Circle().fill(Self.tint(row.tone)).frame(width: 7, height: 7).padding(.top, 6).accessibilityHidden(true)
                Text(row.text).themeFont(13).foregroundStyle(Theme.text)
                    .lineLimit(typeSize.isAccessibilitySize ? nil : 4).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.padding(.horizontal, 12).padding(.vertical, 10).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .background {
                    RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).fill(Theme.surface)
                    RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).fill(Self.tint(row.tone).opacity(0.18))
                }
                .accessibilityElement(children: .combine).accessibilityIdentifier("tool-alert-\(row.name)")
        }
    }
}
