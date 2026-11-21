import SwiftUI

/// Accept a workspace once (ORCH-1204, design ORCH-1027 section 5): on top of its chat while its key is not accepted
/// yet or changed, with the fingerprint to compare and one Accept button. Messages wait (never acted on) until then.
/// A red row says when messages were not shown because they were changed on the way.
struct AcceptWorkspaceCard: View {
    @Environment(AppModel.self) private var model
    var workspaceId: String

    private var name: String {
        model.workspaces.first { $0.id == workspaceId }.map { WorkspaceAlias.name(for: $0) } ?? "This workspace"
    }

    var body: some View {
        let state = model.senderState(workspaceId)
        let waiting = model.held[workspaceId]?.count ?? 0
        let refused = model.notValid[workspaceId]?.count ?? 0
        VStack(spacing: 8) {
            if state == .notAcceptedYet || state == .changed, let fingerprint = model.fingerprint(of: workspaceId) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(state == .changed ? "\(name) has a new fingerprint" : "Accept \(name)?").themeFont(17)
                    Text(fingerprint).font(.system(size: 15, design: .monospaced)).foregroundStyle(Theme.text)
                        .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("accept-fingerprint")
                    Text("Check that it matches the fingerprint \(name) shows on its own Settings page.")
                        .themeFont(13).foregroundStyle(Theme.muted).fixedSize(horizontal: false, vertical: true)
                    if waiting > 0 {
                        Text(waiting == 1 ? "1 message waits until you accept." : "\(waiting) messages wait until you accept.")
                            .themeFont(13).foregroundStyle(Theme.muted)
                    }
                    Button("Accept") { model.acceptWorkspace(workspaceId) }
                        .buttonStyle(WideButtonStyle(color: Theme.brand)).accessibilityIdentifier("accept-workspace")
                }.orchCard().accessibilityElement(children: .contain).accessibilityIdentifier("accept-card-\(workspaceId)")
            }
            if refused > 0 {
                HStack(alignment: .top, spacing: 10) {
                    Circle().fill(Theme.danger).frame(width: 7, height: 7).padding(.top, 6).accessibilityHidden(true)
                    Text(refused == 1 ? "1 message from \(name) was not shown: it was changed on the way."
                                      : "\(refused) messages from \(name) were not shown: they were changed on the way.")
                        .themeFont(13).foregroundStyle(Theme.text).fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }.padding(.horizontal, 12).padding(.vertical, 10).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                    .background {
                        RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).fill(Theme.surface)
                        RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).fill(Theme.danger.opacity(0.18))
                    }
                    .accessibilityElement(children: .combine).accessibilityIdentifier("not-valid-\(workspaceId)")
            }
        }
    }
}
