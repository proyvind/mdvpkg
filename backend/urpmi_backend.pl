#!/usr/bin/perl

##
## Copyright (C) 2010-2011 Mandriva S.A <http://www.mandriva.com>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
##
## Author(s): J. Victor Martins <jvdm@mandriva.com>
##


use warnings;
use strict;

use URPM;
use urpm;
use urpm::media;
use urpm::args;
use urpm::select;


$| = 1;

binmode STDOUT, ':encoding(utf8)';
binmode STDIN, ':encoding(utf8)';

my $urpm = urpm->new_parse_cmdline;
# URPM db, initially not opened
my $db;
urpm::media::configure($urpm);

MAIN: {
    eval {
	defined(my $cmd = <>) or do {
	    close_backend();
	};
	chomp($cmd);

	my %args = ();
	while (<>) {
	    chomp;
	    # empty line means "run command":
	    $_ or do {
		my $task_func = "on_command__$cmd";
		defined $main::{$task_func} 
		    or die "Unknown task name: '$cmd'\n";
		$main::{$task_func}->(%args);
		end();
		# For the eval block:
		return 1;
	    };

	    if (/([^=]+)=(.*)/) {
		$args{$1} = $2;
	    }
	    else {
		$args{$_} = ( $_ =~ s/^~// ? 0 : 1 );
	    }
	}

	die "Malformed command argument: EOF\n";
    }
    or do {
	chomp($@);
	error($@);
    };
    redo MAIN;
}

sub close_backend {
    exit 0;
}

# result - send a result response to caller
sub result {
    _send_response('RESULT', @_);
}

# error - send an error response to caller
sub error {
    _send_response('ERROR', @_);
}

# log - send a log response to caller
sub log {
    _send_response('LOG', @_);
}

sub end {
    _send_response('END', '');
}

sub _send_response {
    my ($tag, $format, @args) = @_;
    printf("%s %s\n", $tag, sprintf($format, @args));
}

sub py_bool_str {
    return $_[0] ? 'True' : 'False';
}

sub py_str {
    $_[0] =~ s|'|\\'|g;
    return "'" . $_[0] . "'";
}    

# py_package_str - returns python string for package data
#
# $pkg		urpm package object
# $tags_ref	array ref to list of package tags to add
# %extra	hash of extra data, keyed by type:
#               ( bool => { name => val }, str => { name => val} )
#
# if not @tags use qw(name version release arch) by default.
#
sub py_package_str {
    my ($pkg, $tags_ref, %extra) = @_;

    # This will hold the final python string:
    my $py_str = "{";

    for my $tag (@$tags_ref) {
	$py_str .= sprintf("'%s':%s,", $tag, py_str($pkg->$tag));
    }

    # Each key provide a helper to produce python string according to
    # $type:
    my %helper = (
	bool => \&py_bool_str,
	str => \&py_str,
	int => sub { sprintf("%d", $_[0] || 0) },
	float => sub { sprintf("%f", $_[0]) },
	);
	  
    foreach my $type (keys %extra) {
	while ( my ($name, $value) = each %{ $extra{$type} } ) {
	    $py_str .= sprintf("'%s':%s,", 
			       $name,
			       $helper{$type}->($value));
	}
    }

    $py_str .= '}';
    return $py_str;
}

sub open_urpm_db {
    if (not $db) {
	# TODO die() if not possible to open:
	$db = URPM::DB::open();
	$urpm->compute_installed_flags($db);
    }
    return $db;
}

##
# traverse_pacakges - traverse all installed and installable packages
#
# $urpm		urpm object
# $db		URPM::DB object
# $callback	$callback->($pkg) for each package
#
# Packages passed to callback have flag_installed and flag_upgrade
# correctly set.
#
sub traverse_packages {
    my ($urpm, $db, $callback) = @_;

    # Traverse installable packages ...
    foreach my $pkg (@{$urpm->{depslist}}) {
        if ($pkg->flag_upgrade) {
	    $callback->($pkg);
	}
    }

    # Traverse installed packages ...
    $db->traverse(
    	sub {
	    my ($pkg) = @_;
	    $pkg->set_flag_installed(1);
	    $pkg->set_flag_upgrade(0);
	    $callback->($pkg);
	}
	);
}

sub get_media_name {
    my ($urpm, $pkg) = @_;

    my $id;
    if ($pkg->id) {
	$id = $pkg->id;
    }
    elsif (my @pkgs = $urpm->packages_by_name($pkg->name)) {
	foreach (@pkgs) {
	    if ($_->fullname() eq $pkg->fullname()) {
		$id = $_->id;
		last;
	    }
	}
    }

    my $media = '';
    if ($id) {
	foreach (@{ $urpm->{media} }) {
	    if ($id >= ($_->{start}||0) and $id <= ($_->{end}||0)) {
		$media = $_->{name};
		last;
	    }
	}
    }
    return $media;
}

sub get_status {
    my ($pkg) = @_;
    
    if ($pkg->flag_installed and not $pkg->flag_upgrade) {
	return 'local';
    }

    if ($pkg->flag_upgrade and $pkg->flag_upgrade) {
	return 'upgrade';
    }

    if (not $pkg->flag_installed and $pkg->flag_upgrade) {
	return 'new';
    }
}

sub filter_package {
    my ($pkg, %filters) = @_;

    %filters or return 1;

    if (my $filter = $filters{'media'}) {
	get_media_name($urpm, $pkg) eq $filter or return 0;
    }

    if (my $filter = $filters{'name'}) {
	$pkg->name eq $filter or return 0;
    }

    if (my $filter = $filters{'group'}) {
	$pkg->group eq $filter or return 0;
    }

    if (exists $filters{'local'}) {
	if ($filters{'local'}) {
	    $pkg->flag_installed && !$pkg->flag_upgrade or return 0;
	}
	else {
	    $pkg->flag_upgrade or return 0;
	}
    }

    if (exists $filters{'upgrade'}) {
	if ($filters{'upgrade'}) {
	    $pkg->flag_upgrade && $pkg->flag_installed or return 0;
	}
	else {
	    not $pkg->flag_upgrade || not $pkg->flag_installed or return 0;
	}
    }

    if (exists $filters{'new'}) {
	if ($filters{'new'}) {
	    $pkg->flag_upgrade && !$pkg->flag_installed or return 0;
	}
	else {
	    $pkg->flag_installed or return 0;
	}
    }

    return 1;
}

#
# Command Handlers
#

sub on_command__list_medias {
    foreach (@{$urpm->{media}}) {
	my ($name, $update, $ignore) 
	    = ($_->{name}, $_->{update}, $_->{ignore});
	result("('%s', %s, %s)", 
	       $name, 
	       py_bool_str($update), 
	       py_bool_str($ignore))
    }
}

sub on_command__list_packages {
    my (%args) = @_;
    my $db = open_urpm_db();

    traverse_packages(
	$urpm,
	$db,
	sub {
	    my ($pkg) = @_;
	    filter_package($pkg, %args) or return;

	    result py_package_str(
		$pkg,
		[ qw(name version release arch epoch group summary) ],
		str => { 
		    status => get_status($pkg)
		},
		int => {
		    size => $pkg->size,
		}
		);
	}
	);
}

sub on_command__list_groups {
    my $db = open_urpm_db();
    my %groups = ();

    traverse_packages(
	$urpm, 
	$db,
	sub {
	    my ($pkg) = @_;
	    my $group = $pkg->group();
	    exists $groups{$group} or $groups{$group} = 0;
	    ++$groups{$group};
	}
	);

    foreach my $group (keys %groups) {
	my $count = $groups{$group};
	result "('$group', $count)";
    }
}

sub on_command__package_details {
    my (%args) = @_;
    my $db = open_urpm_db();

    my $name = $args{name} 
        or die "Missing required parameter: name\n";

    # TODO Download and parse hdlist to provide extra information for
    #      non-installed packages.

    traverse_packages(
	$urpm,
	$db,
	sub {
	    my ($pkg) = @_;
            if ($pkg->name eq $name) {

		my $installtime = 0;
		if ($pkg->flag_installed) {
		    my $name = $pkg->name;
		    $installtime = `rpm -q $name --qf '%{installtime}'`;
		}

		result py_package_str(
		    $pkg, 					 
		    [ qw(name version release arch epoch) ],
		    str => { media => get_media_name($urpm, $pkg) },
		    int => { installtime => $installtime },
		    );
            }
	}
	);
}

sub on_command__search_files {
    my (%args) = @_;
    
    # For each medium, we browse the xml info file, while looking for
    # files which matched with the search term given in argument. We
    # store results in a hash ...

    my %results;

    foreach my $medium (urpm::media::non_ignored_media($urpm)) {
	my $xml_info_file = urpm::media::any_xml_info($urpm,
						      $medium,
						      qw( files summary ),
						      undef,
						      undef);
	$xml_info_file or next;

	require urpm::xml_info;
	require urpm::xml_info_pkg;

	my $F = urpm::xml_info::open_lzma($xml_info_file);
	my $fn;
	local $_;
	my @files = ();
	while (<$F>) {
	    chomp;
	    if (/<files/) {
		($fn) = /fn="(.*)"/;
	    } 
	    elsif (/^$args{pattern}$/ or ($args{fuzzy} and /$args{pattern}/)) {
		my $xml_pkg = urpm::xml_info_pkg->new({ fn => $fn });
		if (not exists $results{$fn}) {
		    $results{$fn} = { pkg => $xml_pkg,
				      files => [] };
		}
		push @{ $results{$fn}{files} }, $_;
	    }
	}
    }

    foreach my $fn (keys %results) {
	my $xml_pkg = $results{$fn}{pkg};
	my $py_str = sprintf("{'name': '%s', "
			         . "'version': '%s', "
			         . "'release': '%s', " 
			         . "'arch': '%s', 'files': [",
	       $xml_pkg->name,
	       $xml_pkg->version,
	       $xml_pkg->release,
	       $xml_pkg->arch);
	$py_str .= sprintf("'%s', ", $_) for (@{ $results{$fn}{files} });
	$py_str .= ']}';
	result($py_str)
    }
}
