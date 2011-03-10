#!/usr/bin/perl

use warnings;
use strict;

use URPM;
use urpm;
use urpm::media;
use urpm::args;
use urpm::select;

$| = 1;

my $urpm = urpm->new_parse_cmdline;
urpm::media::configure($urpm);

while (<>) {
    chomp($_);
    $_ or next;
    my ($cmd, @args) = split /\s+/, $_;
    $main::{"on_command__$cmd"}->(@args);
}

sub to_bool {
    return $_[0] ? 'True' : 'False';
}

sub on_command__list_media {
    foreach (@{$urpm->{media}}) {
	my ($name, $update, $ignore) 
	    = ($_->{name}, $_->{update}, $_->{ignore});
	printf("('%s', %s, %s)\n", $name, to_bool($update), to_bool($ignore))
    }
    print "\n";
}
