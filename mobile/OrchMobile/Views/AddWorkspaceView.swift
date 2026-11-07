import SwiftUI
import UIKit

struct AddWorkspaceView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var linkText = ""
    @State private var link: PairingLink?
    @State private var showField = false
    @State private var scanner = false
    @State private var error: String?
    @State private var busy = false
    @State private var attempted = false
    @State private var added: [WorkspaceRef] = []
    @State private var openAfterDismiss: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack { Text("Add workspace").themeFont(20, .semibold); Spacer(); ShellCloseButton { dismiss() }.disabled(busy) }
                if !added.isEmpty {
                    Text("Added \(added.map(\.displayName).joined(separator: ", "))").themeFont(22, .semibold)
                    ForEach(added) { workspace in
                        Button("Open \(workspace.displayName)") { openAfterDismiss = workspace.id; dismiss() }
                            .buttonStyle(PrimaryButtonStyle())
                    }
                    Button("Done") { dismiss() }.buttonStyle(SecondaryButtonStyle())
                } else if let link {
                    if attempted {
                        Text(model.message ?? "No workspaces were added. Try another invitation.")
                            .themeFont(15).foregroundStyle(Theme.danger).accessibilityIdentifier("invite-error")
                        Button("Try another link") { reset() }.buttonStyle(SecondaryButtonStyle())
                    } else {
                        Text("Add this workspace?").themeFont(22, .semibold)
                        Text("Server: \(link.host)").themeFont(15).foregroundStyle(Theme.muted)
                        DisclosureGroup {
                            Text(link.relay.absoluteString).themeFont(13).textSelection(.enabled).padding(.vertical, 8)
                        } label: { Text("Connection details").themeFont(15).frame(minHeight: 44) }
                        Button {
                            busy = true; model.message = nil
                            Task { added = await model.redeemInvitation(link.link); attempted = true; busy = false }
                        } label: {
                            HStack { if busy { ProgressView().tint(Theme.onBrand) }; Text(busy ? "Adding workspace…" : "Add workspace") }
                        }.buttonStyle(PrimaryButtonStyle()).disabled(busy).accessibilityIdentifier("invite-add")
                        Button("Try another link") { reset() }.buttonStyle(WideButtonStyle(color: Theme.muted)).disabled(busy)
                    }
                } else {
                    Text("Use the invitation for your workspace.").themeFont(13).foregroundStyle(Theme.muted)
                    Button("Scan invitation QR code") { scanner = true }.buttonStyle(PrimaryButtonStyle())
                    Button("Paste invitation link") {
                        if let value = UIPasteboard.general.string, let parsed = try? PairingLink(value) {
                            link = parsed; error = nil
                        } else { showField = true }
                    }.buttonStyle(SecondaryButtonStyle())
                    if showField {
                        TextField("orch://pair?…", text: $linkText).themeFont(16)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                            .textContentType(.URL).submitLabel(.continue).onSubmit { validate(linkText) }
                            .padding(14).background(Theme.surface2, in: RoundedRectangle(cornerRadius: 10))
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(error == nil ? Theme.borderStrong : Theme.danger))
                            .accessibilityLabel("Invitation link").accessibilityIdentifier("invite-field")
                            .onChange(of: linkText) { _, _ in error = nil }
                        Button("Continue") { validate(linkText) }.buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("invite-continue")
                    }
                    if let error { Text(error).themeFont(13).foregroundStyle(Theme.danger).accessibilityIdentifier("invite-error") }
                }
            }.padding(16).padding(.top, 16)
        }.foregroundStyle(Theme.text).background(Theme.surface.ignoresSafeArea())
            .presentationBackground(Theme.surface).presentationDragIndicator(.visible).interactiveDismissDisabled(busy)
            .sheet(isPresented: $scanner) { QRScannerView { code in scanner = false; validate(code) } }
            .onDisappear {
                if let id = openAfterDismiss { model.path = [.workspace(id)] }
            }
    }
    private func validate(_ text: String) {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        showField = true
        guard !clean.isEmpty else { error = "Paste the link you were sent first. It starts with orch://."; return }
        guard let parsed = try? PairingLink(clean) else {
            error = "That link does not look right. Check you copied the whole link, or ask the person who invited you for a new one."
            return
        }
        link = parsed; error = nil
    }
    private func reset() { link = nil; linkText = ""; error = nil; attempted = false; showField = false }
}
